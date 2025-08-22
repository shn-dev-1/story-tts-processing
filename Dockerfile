FROM python:3.10-slim

# System deps (note: libsndfile1 is required by python-soundfile)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    espeak-ng \
    libespeak-dev \
    libsndfile1 \
    ffmpeg \
    gcc g++ make \
  && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# Prewarm Kokoro cache (uses builder's internet)
RUN python - <<'PY'
from kokoro import KPipeline
import soundfile as sf
pipe = KPipeline(lang_code='a')
gen = pipe("cache warmup", voice="af_heart", speed=1.0)
_, _, audio = next(iter(gen))  # force download
sf.write("warmup.wav", audio, 24000)
print("Kokoro prewarmed OK")
PY
RUN rm -f warmup.wav

# Offline + cache location
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/.cache/huggingface \
    TRANSFORMERS_CACHE=/.cache/huggingface/transformers

# Ensure cache is writable after dropping privileges
RUN mkdir -p /.cache/huggingface/transformers && \
    chown -R nobody:nogroup /.cache

# Copy your app (main.py is adjacent to Dockerfile)
COPY main.py /app/main.py

USER nobody
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host=0.0.0.0", "--port=8080"]
