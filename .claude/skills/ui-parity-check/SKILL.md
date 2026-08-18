---
name: ui-parity-check
description: Capture the web UI with headless Playwright at the iPhone's size and compare it against the iOS baselines in docs/ui-parity/. Use after any change that alters how a screen looks, before calling it done, and whenever a screenshot is about to be committed or published.
---

# UI parity check — web vs iOS

Baselines already exist in `docs/ui-parity/` (`ios/`, `web/`, plus a `README.md` listing the 13
screens). Re-capturing overwrites in place, so `git status` after a run *is* the visual diff. Read
that README and `scripts/capture_ui.py` before changing how captures are taken — don't build a
second capture tool.

## ⛔ Hard rule: no LEGO copyrighted content leaves this repo

The repo is public (`github.com/Lunik/Brickseeker-Home`) and explicitly unaffiliated with the LEGO
Group. Set renders from Rebrickable, minifig renders and box photos are copyrighted product
images: **never** put them in the README, in docs, in an issue, or in any new committed image. Set
numbers and names as plain text are factual references and are fine.

The `docs/ui-parity/` baselines are the known exception — `web/03-collection.png`,
`13-fiche-set.png` and friends are full of set renders. They are internal comparison material:
don't extend the breach outside that folder, and never reuse one as a README illustration. A
screen that must be shown publicly gets captured in its empty state, or described in text.

## Capture

The app must be running, and you need a venv with the backend installed — `playwright` and `pillow`
are backend dependencies (`backend/pyproject.toml`). `backend/.venv` is the one the `web-build-test`
skill sets up; any other venv with the backend installed works, so point `VENV` at whichever exists.

```bash
curl -s http://localhost:8000/api/health          # {"status":"ok",...}
VENV=backend/.venv                                # or whatever venv the instance runs from
$VENV/bin/python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); print(b.version); b.close(); p.stop()"
$VENV/bin/python scripts/capture_ui.py --base http://localhost:8000 --out /tmp/ui-new
```

Capture to a scratch dir first, so the repo stays clean until you know what changed. Headless
Chromium, 402×874 logical / DPR 2 / `color_scheme=dark` / `locale=fr-FR` — the iPhone 17 Pro's own
coordinate space, which is why a web shot and a simulator shot lay side by side without rescaling.
`--base` matters: the container is on `:8000`, the script's default is `:8099`. There's no
per-screen flag; the full run is ~55 s, so just run it all.

**Check stderr.** A screen with a `click` step (`05-carte-scans`) whose label doesn't match prints
`note: could not click …` and still writes a PNG — of the screen underneath. In a run against
`:8000` that file came out byte-identical to `04-historique.png`. A silently wrong baseline is
worse than a missing one.

## Compare

```bash
$VENV/bin/python - <<'EOF'
from PIL import Image, ImageChops
from pathlib import Path
for new in sorted(Path("/tmp/ui-new").glob("*.png")):
    old = Path("docs/ui-parity/web") / new.name
    if not old.exists(): print("NEW ", new.name); continue
    a, b = Image.open(old).convert("RGB"), Image.open(new).convert("RGB")
    if a.size != b.size: print("SIZE", new.name, a.size, "->", b.size); continue
    print(("same", "DIFF")[ImageChops.difference(a, b).getbbox() is not None], new.name)
EOF
```

Web-vs-web only. **iOS-vs-web can never be pixel-diffed**: iOS captures are DPR 3 (1206×2622), web
is DPR 2 (804×1748). Compare those by looking — Read `docs/ui-parity/ios/NN-*.png` and the new
shot. The contact-sheet snippet in the parity README checks each file *is* the screen it claims to
be; it is not a diff.

Then copy into `docs/ui-parity/web/` only the screens your change actually altered, same commit.

Diffs that are not regressions: the parity README lists the standing ones (different data between
installs, three missing iOS screens, no camera feed either side, SF Pro narrower than the browser
font). Two more, both observed here — the **accent colour is a stored server-side preference**, so
flipping it turns all 13 files red→amber with no code change; and **`full: True` screens change
height run to run** (`07-statistiques` 4986→3920 px) as the data grows. A `SIZE` line on those is
expected, on a viewport-sized screen it is not.

## Assertions: read the DOM, let Playwright take the pictures

Use the Browser pane (`preview_start`, `resize_window` 402×874 dark) to *drive* a flow: `read_page`
gives stable `ref_N` handles, `form_input` sets a field without touching the OS keyboard,
`read_console_messages` replaces log streaming. But **assert on the DOM, never on the pane's
screenshot** — pane screenshots can lag an in-page DOM update, and their pixel size varies per call
(722×1570 then 800×1739 for the same viewport, scaled to fit). Its reported URL goes stale too: it
kept saying `http://localhost:8000` after a client-side route to `/collection`, while
`get_page_text` returned the current "Ma collection … 1 set sur 499".

## Dropped from the iOS skills, deliberately

Simulator tapping via `mcp__computer-use__*`, the Accessibility/Screen-Recording grants, the AZERTY
`shift+<digit>` typing workaround, re-screenshotting before every click because the window moved,
`simctl launch --console`, the App Shortcuts dead ends — all of it existed because nothing could
address the iOS UI programmatically. Playwright addresses the DOM directly, so none of it has an
equivalent here. `scripts/capture_ios.sh` still needs a hand-navigated simulator for that same
reason, which is why the iOS baselines are refreshed rarely and by hand.
