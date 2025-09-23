# Dockerfile
FROM python:3.11-slim

# System deps for OCR/PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    ghostscript \
    fonts-dejavu \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Python deps first (better cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Runtime dirs (if your code uses them)
RUN mkdir -p /app/assets /app/uploads /app/reports /app/reports_internal \
 && chown -R appuser:appuser /app

ENV PYTHONUNBUFFERED=1 \
    TESSERACT_CMD=tesseract

EXPOSE 8000
USER appuser

# Production server: Gunicorn + Uvicorn workers
# NOTE: your ASGI app is in app.py -> variable "app"
CMD ["gunicorn","-k","uvicorn.workers.UvicornWorker","-w","2","-b","0.0.0.0:8000","api.app:app"]
