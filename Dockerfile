# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:da54eb86849fe19be7584d8b3f291fcf0c53c196760ab3d70dc6382f681ef9c0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
# Optional public CA bundle supplied by the managed build environment only.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY manage.py ./
COPY school_rmm ./school_rmm
COPY inventory ./inventory
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh
RUN chmod -R a+rX /app \
    && SCHOOL_RMM_DEBUG=true SCHOOL_RMM_DATA_DIR=/tmp/static-build \
    python manage.py collectstatic --noinput \
    && install -d -m 0700 -o 10001 -g 10001 /data \
    && install -d -m 0755 -o 10001 -g 10001 /srv/static
USER 10001:10001
ENV SCHOOL_RMM_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8000/healthz/', timeout=4)"
ENTRYPOINT ["sh", "/app/deploy/entrypoint.sh"]
