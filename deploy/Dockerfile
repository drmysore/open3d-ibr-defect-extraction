# IBR Defect Extraction System — Production Container
# Author: Supreeth Mysore
# Program: F135 | Classification: ITAR
#
# ITAR NOTICE: This container image packages software that processes technical
# data subject to the International Traffic in Arms Regulations (ITAR),
# 22 CFR Parts 120-130. This image MUST only be stored in and deployed from
# ITAR-compliant AWS regions (us-east-1, us-west-2). Access is restricted to
# U.S. Persons as defined in 22 CFR 120.15.

FROM python:3.12-slim AS base

LABEL maintainer="Supreeth Mysore" \
      program="F135" \
      classification="ITAR" \
      component="ibr-defect-web" \
      description="IBR Defect Extraction System — FastAPI web application"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -d $APP_HOME -s /sbin/nologin appuser

WORKDIR $APP_HOME

# ── Dependencies ──

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir boto3 psycopg2-binary

# ── Application code ──

COPY src/ ./src/
COPY web/ ./web/
COPY config/ ./config/
COPY data/ ./data/

RUN mkdir -p output models \
    && chown -R appuser:appuser $APP_HOME

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/config || exit 1

CMD ["uvicorn", "web.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--timeout-keep-alive", "120", \
     "--access-log"]
