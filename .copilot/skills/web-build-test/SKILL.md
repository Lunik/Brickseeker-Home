---
name: web-build-test
description: Run the verification loop for the self-hosted web port — TypeScript, the Vite build, ruff, pytest. Use after any frontend or backend change in this repo, before reporting work as done.
---

# Web build & test — BrickSeeker auto-hébergé

Four cheap steps, all of them local. None of them touches a third-party site, so there is never a
reason to skip them.

First time only (`backend/.venv` is gitignored, and `AGENTS.md` assumes it exists):

```bash
cd backend && python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Any Python ≥ 3.12 works; verified here with 3.13.

## Steps

1. **Types** — fast loop while editing the frontend:
   ```bash
   cd frontend && npm run lint          # tsc -b --noEmit
   ```
   This is the only thing that checks the frontend half of `docs/contract.md`. Silence = pass.

2. **Build** — `npm run build` runs `tsc -b && vite build`, so it subsumes step 1 and must be run
   at least once before you call a frontend change done:
   ```bash
   cd frontend && npm run build
   ```
   Output goes to `../backend/app/static/` with `emptyOutDir: true` — that directory is generated
   and gitignored; never edit or commit it. `main.py` serves it with an SPA fallback, so this is
   also what makes a route reachable by URL rather than only by in-app navigation.

3. **Lint the backend**:
   ```bash
   cd backend && .venv/bin/ruff check app
   ```
   Scoped to `app` on purpose: `ruff check .` also reports 5 pre-existing findings in `tests/`
   (4×E501, 1×I001). They are not yours — see AGENTS.md « Portée d'un changement ». Don't run
   `ruff format` either; the repo is not formatted with it (18 files would be rewritten).

4. **Tests** — need a writable data directory:
   ```bash
   cd backend && BRICKSEEKER_DATA_DIR=$(mktemp -d) .venv/bin/pytest -q
   ```
   `app/config.py` calls `ensure_dirs()` at import time, so the default `/data` (a container path)
   fails with `OSError: Read-only file system: '/data'` during *collection* — every test errors
   before any of them runs, which reads like a broken suite and isn't one. Never point it at
   `./data`: that is the live container volume. Expect `64 passed` in about a second.

   What the suite is actually guarding: the pricing kernel's four resolution chains (a wrong one
   is invisible in the UI and wrong everywhere at once) and route declaration order (a literal
   path declared after a parameterised sibling is unreachable — `tests/test_routes.py` exists
   because `POST /collection/bulk` was silently dispatched as `set_num="bulk"`).

Report the change as done only once all four are clean.

## When the Docker rebuild is actually needed

The image **bakes in** both halves: the Dockerfile builds the bundle in stage 1 and
`COPY --from=frontend`s it, then `COPY backend/`. `docker-compose.yml` bind-mounts only
`./data:/data` — no source is mounted. So the container at `:8000` keeps serving the code it was
built with, and a change of any kind is invisible there until:

```bash
docker compose up -d --build
```

Rebuild to ship or to verify something in the real container (Chromium, tesseract, the entrypoint).
Don't rebuild to find out whether code compiles — steps 1–4 answer that in seconds, and the image
carries Chromium at ~1.6 GB.

## Backend and frontend separately, during development

```bash
cd backend && BRICKSEEKER_DATA_DIR=/tmp/bs-dev BRICKSEEKER_SCRAPING_ENABLED=false \
  .venv/bin/uvicorn app.main:app --reload            # API on :8000
cd frontend && npm run dev                           # UI on :5173, proxies /api → :8000
```

Same `/data` trap as the tests: AGENTS.md's bare `uvicorn` line assumes the container's writable
`/data`. `BRICKSEEKER_SCRAPING_ENABLED=false` keeps Chromium from ever launching at
lego.com/Amazon/Cdiscount while you poke at the UI; `/api/health` echoes the flags back — check
`"scraping": false` there, because if the compose container is up it already owns :8000 and you
will be reading *its* health, not your process's. Stop it, or add `--port 8001`.

Check frontend work at **:5173**, not :8000 — the dev server serves your source, while :8000 still
serves the last `npm run build` output.

## Don't

- Don't trigger a full price refresh to "see if it works". It is serial and delayed on purpose
  (AGENTS.md « Le scraping est lent exprès »); hitting the real sites in a loop is what gets an IP
  blacklisted.
- Two iOS rules are dropped here, deliberately: `xcodegen generate` has no counterpart (no
  generated project file — the analogous generated artefact is `backend/app/static/`, and step 2
  regenerates it), and the iOS "there is no test target, don't add one" rule is inverted — this
  port has a suite and step 4 is not optional.
