import os, json, tempfile, uuid, re, threading, sys, time, logging
from pathlib import Path
from typing import Optional

# -------- Custom Exceptions --------
class SQSMessageValidationError(Exception):
    """Raised when an SQS message fails validation."""
    
    def __init__(self, message: str, missing_fields: list = None, received_fields: dict = None):
        self.message = message
        self.missing_fields = missing_fields or []
        self.received_fields = received_fields or {}
        super().__init__(self.message)
    
    def __str__(self):
        return f"SQSMessageValidationError: {self.message}"

# ---- Force HF offline at runtime (no network) ----
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# Optional: point caches somewhere writable in the container
os.environ.setdefault("HF_HOME", "/.cache/huggingface")
os.environ.setdefault("TRANSFORMERS_CACHE", "/.cache/huggingface/transformers")

import boto3
from fastapi import FastAPI
from kokoro import KPipeline  # Kokoro pipeline (Apache-2.0)
import soundfile as sf

# -------- logging --------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

# -------- Config via env --------
QUEUE_URL         = os.getenv("QUEUE_URL") # e.g. https://sqs.us-east-1.amazonaws.com/123/tts-jobs
AWS_REGION        = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_VOICE     = os.getenv("KOKORO_VOICE", "af_heart") # change as desired
DYNAMODB_TABLE    = os.getenv("DYNAMODB_TABLE") # DynamoDB table name from remote state

# Validate required environment variables
if not QUEUE_URL:
    print("[ERROR] QUEUE_URL environment variable is required but not set", file=sys.stderr)
    sys.exit(1)

if not DYNAMODB_TABLE:
    print("[ERROR] DYNAMODB_TABLE environment variable is required but not set", file=sys.stderr)
    sys.exit(1)

# AWS clients
s3   = boto3.client("s3", region_name=AWS_REGION)
sqs  = boto3.client("sqs",  region_name=AWS_REGION)
dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)

# Preload Kokoro (English fast path)
pipeline = KPipeline(lang_code='a')  # 'a' = English voices

app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"ok": True}

# ---------- S3 helpers ----------
def _parse_s3_uri(s3_uri: str):
    assert s3_uri.startswith("s3://"), f"Invalid S3 URI: {s3_uri}"
    _, _, rest = s3_uri.partition("s3://")
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return bucket, key

def _upload_s3(from_path: Path, s3_uri: str):
    bucket, key = _parse_s3_uri(s3_uri)
    s3.upload_file(str(from_path), bucket, key)
    return bucket, key

# ---------- TTS ----------
def synth_to_wav(text: str, wav_path: Path, voice: Optional[str] = None, speed: float = 1.0):
    # Kokoro pipeline yields chunks; stitch to 24 kHz wav
    generator = pipeline(text, voice=(voice or DEFAULT_VOICE), speed=speed, split_pattern=r'\n+')
    audio_out = []
    for _, _, audio in generator:
        audio_out.append(audio)
    import numpy as np
    audio_cat = np.concatenate(audio_out, axis=0) if len(audio_out) > 1 else audio_out[0]
    sf.write(str(wav_path), audio_cat, 24000)

# ---------- Subtitles (SRT) ----------
def write_srt(items, to_path: Path):
    # items: list of (start_sec, end_sec, text)
    def fmt(t):
        ms = int((t - int(t)) * 1000)
        s  = int(t) % 60
        m  = (int(t) // 60) % 60
        h  = int(t) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, (st, et, tx) in enumerate(items, start=1):
        lines += [str(i), f"{fmt(st)} --> {fmt(et)}", (tx or "").strip(), ""]
    to_path.parent.mkdir(parents=True, exist_ok=True)
    to_path.write_text("\n".join(lines), encoding="utf-8")

def align_with_aeneas(wav_path: Path, text: str, srt_path: Path):
    """
    Forced alignment using aeneas with explicit binary paths and debug log.
    Raises if no file is produced so caller can fall back.
    """
    from aeneas.executetask import ExecuteTask
    from aeneas.task import Task
    from aeneas.runtimeconfiguration import RuntimeConfiguration

    cfg = "task_language=eng|is_text_type=plain|os_task_file_format=srt"
    rconf = RuntimeConfiguration()
    rconf[RuntimeConfiguration.FFMPEG_PATH]  = "/usr/bin/ffmpeg"
    rconf[RuntimeConfiguration.FFPROBE_PATH] = "/usr/bin/ffprobe"
    rconf[RuntimeConfiguration.TTS_PATH]     = "/usr/bin/espeak-ng"
    rconf[RuntimeConfiguration.DEBUG_FILE]   = str(srt_path.parent / "aeneas_debug.log")

    with tempfile.TemporaryDirectory() as td:
        txt_path = Path(td) / "script.txt"
        txt = (text or "").strip()
        txt_path.write_text(txt, encoding="utf-8")

        task = Task(config_string=cfg)
        task.audio_file_path_absolute = str(wav_path)
        task.text_file_path_absolute  = str(txt_path)
        task.sync_map_file_path_absolute = str(srt_path)

        log.info("[subs] running aeneas forced alignment")
        ExecuteTask(task, rconf=rconf).execute()

    if not srt_path.exists() or srt_path.stat().st_size == 0:
        raise RuntimeError("Aeneas finished but produced no SRT")

def naive_sentence_srt(text: str, wav_dur_sec: float, srt_path: Path):
    # Basic sentence-splitting fallback when no aligner is used/available
    sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text or "") if s.strip()]
    if not sents:
        sents = [(text or " ").strip()]
    per = max(1.0, wav_dur_sec / max(1, len(sents)))
    items, t = [], 0.0
    for s in sents:
        items.append((t, min(t + per, wav_dur_sec), s))
        t += per
    write_srt(items, srt_path)

def make_subtitles(tts_wav: Path, text: str, subs_srt: Path, use_align: bool):
    """
    Try forced alignment; if it fails or produces nothing, fall back to naive timing.
    Guarantees subs_srt exists with nonzero size on return.
    """
    def duration_sec(p: Path) -> float:
        data, sr = sf.read(str(p))
        return float(len(data)) / float(sr)

    wrote = False
    if use_align and (text or "").strip():
        try:
            align_with_aeneas(tts_wav, text, subs_srt)
            wrote = subs_srt.exists() and subs_srt.stat().st_size > 0
            if not wrote:
                log.warning("[subs] aeneas produced no file; will fall back")
        except Exception as e:
            log.warning(f"[subs] aeneas failed: {e}; will fall back")

    if not wrote:
        dur = duration_sec(tts_wav)
        log.info(f"[subs] writing naive SRT (~{dur:.2f}s)")
        naive_sentence_srt(text, dur, subs_srt)
        wrote = subs_srt.exists() and subs_srt.stat().st_size > 0

    if not wrote:
        # last resort: single cue
        log.error("[subs] creating minimal 1-line SRT fallback")
        dur = duration_sec(tts_wav)
        write_srt([(0.0, max(1.0, dur), text or " ")], subs_srt)

    assert subs_srt.exists() and subs_srt.stat().st_size > 0, "Failed to create subs.srt"

# ---------- DynamoDB helpers ----------
def is_task_completed(parent_id: str, task_id: str) -> bool:
    """
    Check if a task is already completed in DynamoDB.
    
    Args:
        parent_id: The partition key (parent_id)
        task_id: The sort key (tts_task_id or srt_task_id)
    
    Returns:
        bool: True if task is completed, False otherwise
    """
    try:
        response = dynamodb.get_item(
            TableName=DYNAMODB_TABLE,
            Key={
                'parent_id': {'S': parent_id},
                'task_id': {'S': task_id}
            }
        )
        
        if 'Item' in response:
            item = response['Item']
            if 'status' in item and item['status']['S'] == 'COMPLETED':
                return True
        
        return False
        
    except Exception as e:
        log.error(f"[dynamodb] Failed to check task status for {task_id}: {e}")
        raise RuntimeError(f"Unable to verify task status for {task_id}. DynamoDB check failed: {e}") from e

def update_task_status(parent_id: str, task_id: str, status: str, s3_url: str = None):
    """
    Update the status of a task in DynamoDB.
    
    Args:
        parent_id: The partition key (parent_id)
        task_id: The sort key (tts_task_id or srt_task_id)
        status: The status to set
        s3_url: Optional S3 URI to set in the media_url field
    """
    table_name = DYNAMODB_TABLE
    
    try:
        # Build update expression based on status and s3_url
        set_parts = ['#status = :status', '#date_updated = :date_updated']
        expression_attribute_names = {
            '#status': 'status',
            '#date_updated': 'date_updated'
        }
        expression_attribute_values = {
            ':status': {'S': status},
            ':date_updated': {'S': time.strftime('%Y-%m-%dT%H:%M:%S.%fZ', time.gmtime())}
        }
        
        # Add media_url if provided
        if s3_url:
            set_parts.append('#media_url = :media_url')
            expression_attribute_names['#media_url'] = 'media_url'
            expression_attribute_values[':media_url'] = {'S': s3_url}
        
        # Build the update expression with proper comma separation
        update_expression = f"SET {', '.join(set_parts)}"
        
        # Only remove sparse_gsi_hash_key if status is COMPLETED
        if status == "COMPLETED":
            update_expression += " REMOVE sparse_gsi_hash_key"
        
        response = dynamodb.update_item(
            TableName=table_name,
            Key={
                'parent_id': {'S': parent_id},
                'task_id': {'S': task_id}
            },
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues='UPDATED_NEW'
        )
        log.info(f"[dynamodb] Updated task {task_id} status to {status}")
        return response
    except Exception as e:
        log.error(f"[dynamodb] Failed to update task {task_id}: {e}")
        raise

# ---------- Job processor ----------
def process_job(job: dict):
    """
    Expected SQS job message body (JSON):
    {
      "text": "Hello world. This is a test.",
      "parent_id": "12312312", # parent_id of the task
      "tts_task_id": "12312311", # tts_task_id of the task
      "srt_task_id": "12312310", # srt_task_id of the task
      "voice": "af_heart",          # optional
      "speed": 1.0,                 # optional
      "use_alignment": true         # optional; if false => naive timing
    }
    """
    # Handle SNS message envelope - extract the actual message
    actual_job = job
    if "Type" in job and job["Type"] == "Notification" and "Message" in job:
        try:
            # Parse the nested JSON message from SNS
            actual_job = json.loads(job["Message"])
            log.info("[sns] Extracted job from SNS notification envelope")
        except json.JSONDecodeError as e:
            raise SQSMessageValidationError(
                message=f"Failed to parse SNS Message field as JSON: {e}",
                missing_fields=[],
                received_fields=job
            )
    
    # Required fields
    required_fields = ["text", "parent_id", "tts_task_id", "srt_task_id"]
    missing_fields = [field for field in required_fields if field not in actual_job]
    
    if missing_fields:
        raise SQSMessageValidationError(
            message=f"Job missing required fields: {', '.join(missing_fields)}",
            missing_fields=missing_fields,
            received_fields=actual_job
        )

    text         = actual_job["text"]
    parent_id    = actual_job["parent_id"]
    tts_task_id  = actual_job["tts_task_id"]
    srt_task_id  = actual_job["srt_task_id"]

    update_task_status(parent_id, tts_task_id, "IN_PROGRESS")
    update_task_status(parent_id, srt_task_id, "IN_PROGRESS")
    
    # Debug: Log the received job structure
    log.info(f"[debug] Received job: text='{text[:50]}...', parent_id='{parent_id}', tts_task_id='{tts_task_id}', srt_task_id='{srt_task_id}'")
    
    # Check if TTS task is already completed to avoid duplicate processing
    if is_task_completed(parent_id, tts_task_id):
        log.info(f"[skip] TTS task {tts_task_id} already completed, skipping processing")
        return  # Exit early, message will be deleted by caller
    
    log.info(f"[processing] TTS task {tts_task_id} not completed, proceeding with processing")
    audio_s3     = f"s3://story-video-data/{parent_id}/{tts_task_id}.wav"
    subs_s3      = f"s3://story-video-data/{parent_id}/{srt_task_id}.srt"
    voice        = actual_job.get("voice", DEFAULT_VOICE)
    speed        = float(actual_job.get("speed", 1.0))
    use_align    = bool(actual_job.get("use_alignment", True))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tts_wav = td / "tts.wav"
        subs_srt = td / "subs.srt"

        # 1) TTS
        synth_to_wav(text=text, wav_path=tts_wav, voice=voice, speed=speed)
        if not tts_wav.exists():
            raise FileNotFoundError(f"TTS wav missing: {tts_wav}")

        # 2) Subtitles (robust)
        make_subtitles(tts_wav, text, subs_srt, use_align=use_align)

        # 3) Upload results to S3
        _upload_s3(tts_wav, audio_s3)
        _upload_s3(subs_srt, subs_s3)
        log.info(f"[done] uploaded wav -> {audio_s3}, srt -> {subs_s3}")

        # 4) Update DynamoDB task status to COMPLETED with S3 URIs
        update_task_status(parent_id, tts_task_id, "COMPLETED", audio_s3)
        update_task_status(parent_id, srt_task_id, "COMPLETED", subs_s3)
        log.info(f"[done] updated DynamoDB tasks {tts_task_id} and {srt_task_id} to COMPLETED")

# ---------- Worker loop ----------
def worker_loop():
    print("[worker] starting SQS long-poll loop")
    if not QUEUE_URL:
        print("[worker] QUEUE_URL is not set; exiting worker loop.", file=sys.stderr)
        return

    while True:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,         # long poll
            VisibilityTimeout=300       # adjust to your job time
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            continue

        for m in msgs:
            rcpt = m["ReceiptHandle"]
            try:
                # Debug: Log the raw message structure
                print(f"[debug] Raw SQS message: {m}")
                print(f"[debug] Message body: {m['Body']}")
                
                job = json.loads(m["Body"])
                print(f"[debug] Parsed job: {job}")
                
                process_job(job)
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=rcpt)
            except SQSMessageValidationError as e:
                print(f"[worker] SQS message validation failed: {e}", file=sys.stderr)
                if e.missing_fields:
                    print(f"[worker] Missing fields: {e.missing_fields}", file=sys.stderr)
                if e.received_fields:
                    print(f"[worker] Received fields: {list(e.received_fields.keys())}", file=sys.stderr)
                
            except Exception as e:
                print(f"[worker] job failed: {e}", file=sys.stderr)
                
                # If validation passed but processing failed, update task statuses to FAILED
                try:
                    # Extract the actual job data (in case it's wrapped in SNS envelope)
                    actual_job_for_status = job
                    if "Type" in job and job["Type"] == "Notification" and "Message" in job:
                        try:
                            actual_job_for_status = json.loads(job["Message"])
                        except json.JSONDecodeError:
                            actual_job_for_status = job  # Fall back to original
                    
                    # Extract task IDs from the actual job for status update
                    if 'parent_id' in actual_job_for_status and 'tts_task_id' in actual_job_for_status and 'srt_task_id' in actual_job_for_status:
                        parent_id = actual_job_for_status['parent_id']
                        tts_task_id = actual_job_for_status['tts_task_id']
                        srt_task_id = actual_job_for_status['srt_task_id']
                        
                        # Update both task statuses to FAILED
                        update_task_status(parent_id, tts_task_id, "FAILED")
                        update_task_status(parent_id, srt_task_id, "FAILED")
                        print(f"[worker] Updated task statuses to FAILED for TTS: {tts_task_id}, SRT: {srt_task_id}")
                    else:
                        print("[worker] Could not update task statuses - missing required fields in job", file=sys.stderr)
                        
                except Exception as status_error:
                    print(f"[worker] Failed to update task statuses to FAILED: {status_error}", file=sys.stderr)

# ---------- App startup ----------
@app.on_event("startup")
def _start_worker():
    if not QUEUE_URL:
        print("[startup] QUEUE_URL not set; worker will not start.", file=sys.stderr)
        return
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
