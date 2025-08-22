import os, json, tempfile, uuid, re, threading, sys, time
from pathlib import Path
from typing import Optional

import boto3
from fastapi import FastAPI
from kokoro import KPipeline  # Kokoro pipeline (Apache-2.0)
import soundfile as sf

# -------- Config via env --------
QUEUE_URL         = os.getenv("QUEUE_URL")                # e.g. https://sqs.us-east-1.amazonaws.com/123/tts-jobs
AWS_REGION        = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_VOICE     = os.getenv("KOKORO_VOICE", "af_heart") # change as desired

# Validate required environment variables
if not QUEUE_URL:
    print("[ERROR] QUEUE_URL environment variable is required but not set", file=sys.stderr)
    sys.exit(1)

# AWS clients
s3   = boto3.client("s3", region_name=AWS_REGION)
sqs  = boto3.client("sqs",  region_name=AWS_REGION)

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
        lines += [str(i), f"{fmt(st)} --> {fmt(et)}", tx.strip(), ""]
    to_path.write_text("\n".join(lines), encoding="utf-8")

def align_with_aeneas(wav_path: Path, text: str, srt_path: Path):
    # Forced alignment using aeneas (if installed per requirements.txt)
    from aeneas.executetask import ExecuteTask
    from aeneas.task import Task
    cfg = "task_language=eng|is_text_type=plain|os_task_file_format=srt"
    with tempfile.TemporaryDirectory() as td:
        txt_path = Path(td) / "script.txt"
        txt_path.write_text(text, encoding="utf-8")
        task = Task(config_string=cfg)
        task.audio_file_path_absolute = str(wav_path)
        task.text_file_path_absolute  = str(txt_path)
        task.sync_map_file_path_absolute = str(srt_path)
        ExecuteTask(task).execute()

def naive_sentence_srt(text: str, wav_dur_sec: float, srt_path: Path):
    # Basic sentence-splitting fallback when no aligner is used/available
    sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sents:
        sents = [text.strip()]
    per = max(1.0, wav_dur_sec / max(1, len(sents)))
    items, t = [], 0.0
    for s in sents:
        items.append((t, min(t + per, wav_dur_sec), s))
        t += per
    write_srt(items, srt_path)

# ---------- Job processor ----------
def process_job(job: dict):
    """
    Expected SQS job message body (JSON):
    {
      "text": "Hello world. This is a test.",
      "audio_out": "s3://my-bucket/out/job-123/audio.wav",
      "subs_out":  "s3://my-bucket/out/job-123/subs.srt",
      "voice": "af_heart",          # optional
      "speed": 1.0,                 # optional
      "use_alignment": true         # optional; if false => naive timing
    }
    """
    # Required fields
    if "text" not in job or "audio_out" not in job or "subs_out" not in job:
        raise ValueError("Job must include 'text', 'audio_out', and 'subs_out' fields.")

    text         = job["text"]
    audio_s3     = job["audio_out"]
    subs_s3      = job["subs_out"]
    voice        = job.get("voice", DEFAULT_VOICE)
    speed        = float(job.get("speed", 1.0))
    use_align    = bool(job.get("use_alignment", True))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tts_wav = td / "tts.wav"
        subs_srt = td / "subs.srt"

        # 1) TTS
        synth_to_wav(text=text, wav_path=tts_wav, voice=voice, speed=speed)

        # 2) Subtitles
        if use_align:
            try:
                align_with_aeneas(tts_wav, text, subs_srt)
            except Exception as e:
                print(f"[align] aeneas failed: {e}; falling back to naive timing", file=sys.stderr)
                data, sr = sf.read(str(tts_wav))
                dur = len(data) / sr
                naive_sentence_srt(text, dur, subs_srt)
        else:
            data, sr = sf.read(str(tts_wav))
            dur = len(data) / sr
            naive_sentence_srt(text, dur, subs_srt)

        # 3) Upload results to S3
        _upload_s3(tts_wav, audio_s3)
        _upload_s3(subs_srt, subs_srt)

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
                job = json.loads(m["Body"])
                process_job(job)
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=rcpt)
            except Exception as e:
                print(f"[worker] job failed: {e}", file=sys.stderr)
                # Consider: DLQ or ChangeMessageVisibility here.

# ---------- App startup ----------
@app.on_event("startup")
def _start_worker():
    if not QUEUE_URL:
        print("[startup] QUEUE_URL not set; worker will not start.", file=sys.stderr)
        return
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
