#!/usr/bin/env python3
"""Capture the web app's screens as PNGs, for side-by-side comparison with the iOS app.

Every screen is shot at the iPhone's own logical size (402×874) so a web capture and a simulator
capture can be laid next to each other without rescaling either.

    python3 scripts/capture_ui.py --out docs/ui-parity/web --base http://localhost:8099

Pair it with `capture_ios.sh`, which drives the simulator. Both write into `docs/ui-parity/`, and
re-running either overwrites in place — so `git status` after a run *is* the visual diff.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

#: iPhone 17 Pro logical size, matching the simulator's coordinate space.
VIEWPORT = {"width": 402, "height": 874}

#: Every screen worth a baseline. `wait` is extra settle time for the ones that fetch on mount and
#: reflow once the data lands — a screenshot taken mid-skeleton is a useless baseline.
SCREENS: list[dict] = [
    {"name": "01-accueil", "path": "/", "wait": 1500},
    {"name": "02-scanner", "path": "/scan", "wait": 1200},
    {"name": "03-collection", "path": "/collection", "wait": 2500},
    {"name": "04-historique", "path": "/history", "wait": 1500},
    {"name": "05-carte-scans", "path": "/history", "wait": 1500, "click": "Voir la carte des scans"},
    {"name": "06-liste-cadeaux", "path": "/wishlist", "wait": 2500},
    {"name": "07-statistiques", "path": "/stats", "wait": 2500, "full": True},
    {"name": "08-minifigs", "path": "/minifigs", "wait": 2500},
    {"name": "09-nouveaux-sets", "path": "/new-sets", "wait": 2500},
    {"name": "10-alertes", "path": "/alerts", "wait": 1200},
    {"name": "11-parametres", "path": "/settings", "wait": 1500, "full": True},
    {"name": "12-onboarding", "path": "/onboarding", "wait": 800},
]

#: Filled in at runtime with a real set number, so the detail baseline shows a populated screen
#: rather than an empty shell.
SET_DETAIL = {"name": "13-fiche-set", "path": "/set/{set_num}", "wait": 4000, "full": True}


async def first_set_num(page, base: str) -> str | None:
    """Any owned set, so the detail capture has prices, scans and galleries to show."""
    try:
        response = await page.request.get(f"{base}/api/collection")
        payload = await response.json()
        sets = payload.get("sets") or []
        return sets[0]["setNum"] if sets else None
    except Exception:  # noqa: BLE001 - the detail shot is a nicety, not the point of the run
        return None


async def capture(base: str, out_dir: Path, theme: str) -> int:
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=2,
            color_scheme=theme,
            locale="fr-FR",
        )
        page = await context.new_page()

        screens = list(SCREENS)
        set_num = await first_set_num(page, base)
        if set_num:
            detail = dict(SET_DETAIL)
            detail["path"] = detail["path"].format(set_num=set_num)
            screens.append(detail)
        else:
            print("note: no set in the collection — skipping the detail capture", file=sys.stderr)

        for screen in screens:
            url = f"{base}{screen['path']}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:
                # networkidle never settles on a screen that polls; the load itself is enough.
                pass
            await page.wait_for_timeout(screen.get("wait", 1000))

            label = screen.get("click")
            if label:
                try:
                    await page.get_by_text(label, exact=False).first.click(timeout=5000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    print(f"note: could not click {label!r} on {screen['name']}", file=sys.stderr)

            destination = out_dir / f"{screen['name']}.png"
            await page.screenshot(path=destination, full_page=screen.get("full", False))
            written += 1
            print(f"✓ {destination.relative_to(Path.cwd()) if destination.is_relative_to(Path.cwd()) else destination}")

        await browser.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture the web app's screens for UI comparison.")
    parser.add_argument("--base", default="http://localhost:8099", help="running BrickSeeker instance")
    parser.add_argument("--out", type=Path, default=Path("docs/ui-parity/web"))
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    args = parser.parse_args()

    written = asyncio.run(capture(args.base.rstrip("/"), args.out, args.theme))
    print(f"\n{written} capture(s) dans {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
