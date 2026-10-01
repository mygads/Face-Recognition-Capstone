FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /service

ARG SERVICE_PATH
COPY ${SERVICE_PATH}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_PATH}/src ./src
RUN python -m pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
