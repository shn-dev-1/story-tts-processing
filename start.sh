#!/bin/bash

# Story TTS Processing Startup Script

# Check if required environment variables are set
if [ -z "$QUEUE_URL" ]; then
    echo "Error: QUEUE_URL environment variable is required"
    echo "Please set it to your SQS queue URL:"
    echo "export QUEUE_URL='https://sqs.us-east-1.amazonaws.com/123/tts-jobs'"
    exit 1
fi

# Set default values for optional variables
export AWS_REGION=${AWS_REGION:-"us-east-1"}
export KOKORO_VOICE=${KOKORO_VOICE:-"af_heart"}

echo "Starting Story TTS Processing..."
echo "Queue URL: $QUEUE_URL"
echo "AWS Region: $AWS_REGION"
echo "Kokoro Voice: $KOKORO_VOICE"
echo ""

# Start the FastAPI application
uvicorn main:app --host 0.0.0.0 --port 8000
