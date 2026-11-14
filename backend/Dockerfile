FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \n    MALLOC_ARENA_MAX=2
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY aeon ./aeon
EXPOSE 8000
# WEB_CONCURRENCY web workers (default 2); each runs AEON_HEAVY_WORKERS heavy-job processes (default 1).
# Rule of thumb: (WEB_CONCURRENCY x (1 + AEON_HEAVY_WORKERS)) <= CPU cores; ~0.5 GB RAM per process.
CMD ["sh", "-c", "exec uvicorn aeon.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
