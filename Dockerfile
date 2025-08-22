FROM python:3.10-slim

# Install system dependencies and build tools
RUN apt-get update && apt-get install -y \
    espeak-ng \
    ffmpeg \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install numpy first (required by aeneas)
RUN pip install --no-cache-dir numpy

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p outputs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose port for FastAPI
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
