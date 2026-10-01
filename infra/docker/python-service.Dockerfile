FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /service

ARG SERVICE_PATH
ARG SERVICE_EXTRAS=dev
ARG INSTALL_RECOGNITION_CORE=false
COPY ${SERVICE_PATH}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_PATH}/src ./src
COPY libs/recognition-core /recognition-core
RUN if [ "$INSTALL_RECOGNITION_CORE" = "true" ]; then \
      python -m pip install --no-cache-dir -e "/recognition-core[opencv]"; \
    fi \
    && python -m pip install --no-cache-dir -e ".[${SERVICE_EXTRAS}]"

EXPOSE 8000
