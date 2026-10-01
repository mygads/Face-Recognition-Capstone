FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/presensi

COPY libs/recognition-core/pyproject.toml ./libs/recognition-core/pyproject.toml
COPY libs/recognition-core/src ./libs/recognition-core/src
COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY apps/api/src ./apps/api/src
COPY apps/api/migrations ./apps/api/migrations
COPY apps/api/alembic.ini ./apps/api/alembic.ini

RUN python -m pip install --no-cache-dir \
      "/opt/presensi/libs/recognition-core[opencv]" \
      "/opt/presensi/apps/api" \
    && groupadd --system --gid 10001 presensi \
    && useradd --system --uid 10001 --gid presensi \
      --no-create-home --home-dir /nonexistent presensi

WORKDIR /opt/presensi/apps/api
USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "presensi_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
