FROM python:3.12-slim

# ffmpeg (built with librubberband on Debian) does mastering and pitch shifting
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Kokoro voice model into the image so cold starts don't download 350 MB
RUN mkdir -p models \
 && curl -fsSL -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
 && curl -fsSL -o models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY storybook ./storybook
COPY server ./server
COPY site ./site
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1 \
    STORYBOOK_DATA=/data \
    STORYBOOK_CACHE=/data/tts-cache
RUN mkdir -p /data

EXPOSE 8080
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
