FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what runs (see .dockerignore): the API and the web client.
COPY app app
COPY web web

# Cloud Run runs its own health checks against /health; no HEALTHCHECK here.
RUN useradd --system --uid 10001 --no-create-home app
USER app

# Cloud Run requires apps to listen on 0.0.0.0:8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
