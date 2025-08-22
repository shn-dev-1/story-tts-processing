# Story TTS Processing

A FastAPI-based Python application that processes SQS messages to generate Text-to-Speech (TTS) audio and aligned subtitles using Kokoro for TTS generation and Aeneas for subtitle alignment.

## Features

- **FastAPI Web Server**: RESTful API with health check endpoint
- **SQS Integration**: Polls SQS queue for TTS job messages
- **Kokoro TTS**: High-quality text-to-speech using Kokoro pipeline
- **Subtitle Alignment**: Uses Aeneas for precise timing, with fallback to naive sentence splitting
- **S3 Output**: Automatically uploads generated audio and subtitle files to S3
- **Configurable**: Voice selection, speed control, and alignment options
- **300s Visibility Timeout**: Ensures long TTS generation doesn't cause message loss

## Architecture

- **FastAPI Server**: Provides `/healthz` endpoint and manages worker thread
- **Worker Thread**: Background SQS polling with long-polling (20s wait time)
- **TTS Pipeline**: Kokoro pipeline for high-quality speech synthesis
- **Subtitle Generation**: Aeneas for forced alignment or naive timing fallback
- **S3 Integration**: Automatic upload of results to specified S3 locations

## Prerequisites

- Python 3.8+
- AWS credentials configured with S3 and SQS access
- Access to the SQS queue specified in `QUEUE_URL`
- S3 bucket for output files

## Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd story-tts-processing
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Aeneas system dependencies (optional):
```bash
# On macOS
brew install espeak

# On Ubuntu/Debian
sudo apt-get install espeak-ng

# On Windows
# Download and install eSpeak from http://espeak.sourceforge.net/
```

## Configuration

Set environment variables:

```bash
# Required
export QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123/tts-jobs"
export AWS_REGION="us-east-1"

# Optional
export KOKORO_VOICE="af_heart"  # Default voice
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
```

## Usage

### Running the Application

Start the FastAPI server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Or run directly:
```bash
python main.py
```

### SQS Message Format

Messages should have this JSON structure:
```json
{
  "text": "Hello world. This is a test.",
  "audio_out": "s3://my-bucket/out/job-123/audio.wav",
  "subs_out": "s3://my-bucket/out/job-123/subs.srt",
  "voice": "af_heart",          // optional
  "speed": 1.0,                 // optional
  "use_alignment": true         // optional; if false => naive timing
}
```

### API Endpoints

- `GET /healthz` - Health check endpoint

## Output

The application generates:
- **Audio File**: 24kHz WAV file uploaded to specified S3 location
- **Subtitle File**: SRT format with precise timing (Aeneas) or sentence-based timing (fallback)

## Kokoro Voices

Available voices include:
- `af_heart` - Default voice
- Additional voices can be configured via `KOKORO_VOICE` environment variable

## Error Handling

- **Aeneas Failure**: Automatically falls back to naive sentence timing
- **SQS Processing**: Failed jobs remain in queue for retry
- **S3 Upload**: Errors are logged and can trigger retry logic
- **Worker Thread**: Daemon thread ensures clean shutdown

## Docker Deployment

Build and run with Docker:
```bash
docker build -t story-tts .
docker run -e QUEUE_URL="your-queue-url" -e AWS_REGION="us-east-1" story-tts
```

Or use docker-compose:
```bash
docker-compose up --build
```

## Monitoring

- **Health Check**: `/healthz` endpoint for load balancer health checks
- **Logging**: Console output with worker status and job processing
- **SQS Metrics**: Monitor queue depth and processing time
- **S3 Access**: Track file uploads and storage usage

## Performance

- **Long Polling**: 20-second SQS wait time reduces API calls
- **Batch Processing**: Processes one message at a time for reliability
- **Memory Efficient**: Temporary files cleaned up automatically
- **Async Ready**: FastAPI foundation for potential async improvements

## Troubleshooting

1. **QUEUE_URL Not Set**: Worker thread won't start; check environment variables
2. **Aeneas Installation**: Ensure eSpeak is installed for subtitle alignment
3. **S3 Permissions**: Verify AWS credentials have S3 upload access
4. **Kokoro Model**: Check Kokoro installation and voice availability

## Development

- **Local Testing**: Use `uvicorn main:app --reload` for development
- **Message Testing**: Send test messages to SQS queue
- **Voice Testing**: Experiment with different Kokoro voices
- **Alignment Testing**: Test both Aeneas and naive timing modes

## License

[Your License Here]
