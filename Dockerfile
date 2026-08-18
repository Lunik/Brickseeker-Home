# syntax=docker/dockerfile:1
#
# One image, one container: the Vite bundle is built in stage 1 and copied into the Python
# package in stage 2, so uvicorn serves both the API and the UI from the same origin.
#
# The image is large (~1.6 GB) and that is inherent, not sloppiness: lego.com sits behind a
# Cloudflare Managed Challenge and Amazon/Cdiscount behind their own bot checks, none of which a
# plain HTTP client can pass — a real browser engine is the only thing that gets through, so
# Chromium ships with the app. Set BRICKSEEKER_SCRAPING_ENABLED=false to run without it; BrickLink
# (a signed API call) and everything else keep working.

# --------------------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    BRICKSEEKER_DATA_DIR=/data

# tesseract replaces iOS's Vision framework for reading the set number off a box photo;
# the -fra pack matters because French packaging is the common case for this user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
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

# Chromium + its system libraries. Kept in its own layer so a code change doesn't re-download it.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

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
