import os

# AWS Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

# SQS Configuration
SQS_QUEUE_NAME = 'story-sqs-queue-tts'
SQS_VISIBILITY_TIMEOUT = 300  # seconds
SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME = 20  # seconds

# TTS Configuration
TTS_MODEL_NAME = "microsoft/DialoGPT-medium"  # Replace with actual Kokoro-84M model
TTS_SAMPLE_RATE = 22050
TTS_DEVICE = "cuda" if os.getenv('USE_CUDA', 'true').lower() == 'true' else "cpu"

# Output Configuration
OUTPUT_BASE_DIR = "outputs"
AUDIO_FORMAT = "wav"
SUBTITLE_FORMAT = "srt"

# Aeneas Configuration
AENEAS_LANGUAGE = "eng"
AENEAS_TASK_FORMAT = "srt"
AENEAS_TEXT_TYPE = "plain"
