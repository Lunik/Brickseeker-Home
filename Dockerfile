# syntax=docker/dockerfile:1
#
# The Vite bundle is built in stage 1 and copied into the Python package in stage 2, so uvicorn
# serves both the API and the UI from the same origin.
#
# This image does NOT bundle Chromium. lego.com sits behind a Cloudflare Managed Challenge and
# Amazon/Cdiscount behind their own bot checks, none of which a plain HTTP client can pass — a
# real browser engine is the only thing that gets through, but that engine is heavy (~1 GB with
# its system libs) and gets its own container instead: see the `chromium` service in
# docker-compose.yml, and BRICKSEEKER_BROWSER_WS_ENDPOINT in config.py, which points this image
# at it over CDP. Running this image without that sidecar (or the env var pointed at some other
# CDP endpoint) leaves lego.com/Amazon/Cdiscount prices unavailable even with scraping enabled.
# Set BRICKSEEKER_SCRAPING_ENABLED=false to turn that path off outright; BrickLink (a signed API
# call) and everything else keep working either way.

# --------------------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
# What the footer reports. Passed by CI as the git tag being released; without it the build falls
# back to `git describe`, which finds no repository here and settles on "dev" — correct for an
# image somebody built by hand from a working copy.
ARG BRICKSEEKER_VERSION
ENV BRICKSEEKER_VERSION=${BRICKSEEKER_VERSION}
RUN npm run build


# --------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BRICKSEEKER_DATA_DIR=/data

# No tesseract here: OCR runs entirely on-device (tesseract.js, bundled into the frontend build),
# never server-side — see frontend/src/lib/offline-ocr.ts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app/__init__.py ./backend/app/__init__.py
# Editable, not a normal install: at this point `backend/app/` holds nothing but `__init__.py` (kept
# minimal on purpose, so a code-only change doesn't bust this layer and force every dependency to
# reinstall) — a normal `pip install` would copy *that* into site-packages as the whole `app`
# package. Editable only registers a path redirect, so it resolves against whatever is actually in
# `/app/backend/app/` once the real tree lands below, rather than the empty stub frozen at this step.
RUN pip install --no-cache-dir -e ./backend

COPY backend/ ./backend/
# `outDir: '../backend/app/static'` from /build resolves to /backend/app/static in that stage.
COPY --from=frontend /backend/app/static ./backend/app/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Runs as a non-root user; /data is the only path that needs to be writable and is a volume.
RUN useradd --create-home --uid 1000 brickseeker \
    && mkdir -p /data \
    && chown -R brickseeker:brickseeker /data /app
USER brickseeker

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
