FROM python:3.10-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    espeak-ng \
    libespeak-dev \
    libsndfile1 \
    ffmpeg \
    gcc g++ make \
    libxml2-dev libxslt1-dev zlib1g-dev pkg-config \
  && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# --- Use ONE cache path for both build-time prewarm AND runtime ---
ENV HF_HOME=/opt/hfcache \
    HUGGINGFACE_HUB_CACHE=/opt/hfcache/hub \
    TRANSFORMERS_CACHE=/opt/hfcache/transformers \
    HF_HUB_DISABLE_TELEMETRY=1

# Create cache dirs and make them writable later
RUN mkdir -p /opt/hfcache/hub /opt/hfcache/transformers

WORKDIR /app
COPY requirements.txt /app/

# Tooling + numpy before aeneas
RUN pip install --upgrade pip setuptools wheel && \
    pip install numpy && \
    pip install -r requirements.txt

# --- PREWARM into /opt/hfcache (same path we use at runtime) ---
RUN python - <<'PY'
import os
# make sure offline is NOT set during prewarm
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)
from kokoro import KPipeline
import soundfile as sf
pipe = KPipeline(lang_code='a')                 # loads model into HF cache
gen = pipe("cache warmup", voice="af_heart")    # pull voice assets too
_, _, audio = next(iter(gen))
sf.write("warmup.wav", audio, 24000)
print("Kokoro prewarmed into", os.getenv("HF_HOME"))
PY
RUN rm -f warmup.wav

# --- NOW force offline for runtime, keep same cache path ---
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Ensure app user can read the cache
RUN chown -R nobody:nogroup /opt/hfcache

# Your app (main.py is adjacent to Dockerfile)
COPY main.py /app/main.py

USER nobody
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host=0.0.0.0", "--port=8080"]
