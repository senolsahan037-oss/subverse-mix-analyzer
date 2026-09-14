FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libsndfile1 git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY subverse ./subverse
COPY docs ./docs
COPY assets ./assets
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["sh", "-c", "uvicorn subverse.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
