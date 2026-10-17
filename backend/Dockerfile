FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# один образ на два контейнера: api (uvicorn) и collector (python -m app.collector)
RUN useradd --system --uid 10001 app && mkdir -p /data && chown app /data
USER app

# git sha сборки для /api/health (deploy.sh: GIT_SHA=… docker compose up --build); последним слоем — кэш выше не сбивается
ARG GIT_SHA=unknown
ENV BUILD_SHA=$GIT_SHA

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
