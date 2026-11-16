# syntax=docker/dockerfile:1
# One image, both transports:
#   docker run -p 8000:8000 IMAGE         -> HTTP on $PORT (default 8000; GET /health)
#   docker run -i IMAGE stdio             -> stdio worker, for DuckDB on the same host
FROM python:3.14-slim

# Runtime libraries required by the scientific manylinux wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

ARG VERSION=0.0.0
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="vgi-trajectory-worker" \
      org.opencontainers.image.description="A VGI worker for DuckDB" \
      org.opencontainers.image.source="https://github.com/Query-farm/vgi-starter-python" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.licenses="0BSD"

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8000
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable && rm /usr/local/bin/uv
ENV PATH="/app/.venv/bin:$PATH" NUMBA_CACHE_DIR=/home/worker/.cache/numba \
    XDG_STATE_HOME=/var/lib/vgi OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 worker \
    && mkdir -p /var/lib/vgi && chown worker:worker /var/lib/vgi
USER worker

COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=2)"
ENTRYPOINT ["docker-entrypoint.sh"]
