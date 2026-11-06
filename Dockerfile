# CPU image: web UI + script generation + Gemini TTS through the BAZE gateway.
# Local Raon voice cloning needs the GPU extra and is not part of this image.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libreoffice-impress poppler-utils fonts-noto-cjk fonts-nanum \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
EOF
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY lecture_auto ./lecture_auto
COPY scripts ./scripts
COPY config ./config
COPY data/audio_ref ./data/audio_ref
COPY docker/entrypoint.sh /entrypoint.sh

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 LECTURE_WEB_ROOT=/data
VOLUME ["/data"]
EXPOSE 8800
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "lecture_auto.web", "--host", "0.0.0.0", "--port", "8800"]
