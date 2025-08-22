FROM python:3.10-slim

# System deps (incl. libsndfile1 for soundfile, espeak-ng for aeneas)
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

WORKDIR /app
COPY requirements.txt /app/

# 1) Upgrade build tooling and install NumPy FIRST (aeneas requires it during setup)
RUN pip install --upgrade pip setuptools wheel && \
    pip install numpy

# 2) Now install the rest (this can include aeneas safely)
RUN pip install -r requirements.txt

# Prewarm Kokoro cache (uses builder's internet)
RUN python - <<'PY'
from kokoro import KPipeline
import soundfile as sf
pipe = KPipeline(lang_code='a')
gen = pipe("cache warmup", voice="af_heart", speed=1.0)
_, _, audio = next(iter(gen))  # force download of voice/assets
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

# Your app is adjacent to Dockerfile
COPY main.py /app/main.py

USER nobody
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host=0.0.0.0", "--port=8080"]
