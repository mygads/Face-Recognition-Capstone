FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/presensi

COPY libs/recognition-core/pyproject.toml ./libs/recognition-core/pyproject.toml
COPY libs/recognition-core/src ./libs/recognition-core/src
COPY apps/ai-service/pyproject.toml ./apps/ai-service/pyproject.toml
COPY apps/ai-service/src ./apps/ai-service/src

RUN python -m pip install --no-cache-dir \
      "/opt/presensi/libs/recognition-core[opencv]" \
      "/opt/presensi/apps/ai-service[inference]" \
    && groupadd --system --gid 10002 presensi-ai \
    && useradd --system --uid 10002 --gid presensi-ai \
      --no-create-home --home-dir /nonexistent presensi-ai

WORKDIR /opt/presensi/apps/ai-service
USER 10002:10002
EXPOSE 8001

# The gallery cache, rate limiter, temporal evidence, and metrics are process-local.
CMD ["uvicorn", "presensi_ai_service.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
