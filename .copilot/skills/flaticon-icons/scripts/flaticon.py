#!/usr/bin/env python3
"""Search, download and normalise Flaticon SVG icons.

Stdlib only, so it runs anywhere Python does with no install step.

The API key is read from `FLATICON_API_KEY`, falling back to `~/.config/flaticon/api_key`. The
short-lived bearer token is cached in `~/.config/flaticon/token.json` so a run of several
downloads authenticates once.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.flaticon.com/v3"
CONFIG_DIR = Path.home() / ".config" / "flaticon"
TOKEN_CACHE = CONFIG_DIR / "token.json"
#: Flaticon's published limit is far higher, but downloads are sequential and polite by default.
DOWNLOAD_DELAY_SECONDS = 0.4


class FlaticonError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------------


def _api_key() -> str:
    key = os.environ.get("FLATICON_API_KEY")
    if key:
        return key.strip()
    key_file = CONFIG_DIR / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    raise FlaticonError(
        "No Flaticon API key. Set FLATICON_API_KEY, or write it to ~/.config/flaticon/api_key "
        "(get one at https://developers.flaticon.com/)."
    )


def _request(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:400]
        if error.code == 401:
            raise FlaticonError(
                "Flaticon rejected the credentials (401). The key may be wrong, or the cached "
                f"token expired — delete {TOKEN_CACHE} and retry. Response: {detail}"
            ) from error
        if error.code == 403:
            raise FlaticonError(
                "Flaticon refused the request (403). This usually means the plan does not cover "
                f"this icon or format. Response: {detail}"
            ) from error
        if error.code == 429:
            raise FlaticonError("Rate limited by Flaticon (429). Wait a moment and retry.") from error
        raise FlaticonError(f"Flaticon returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise FlaticonError(f"Could not reach Flaticon: {error.reason}") from error


def _token() -> str:
    if TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            # A minute of slack: a token that expires mid-run is the confusing failure.
            if cached.get("expires", 0) > time.time() + 60:
                return cached["token"]
        except (json.JSONDecodeError, KeyError):
            pass

    payload, _ = _request(f"{API_BASE}/app/authentication", method="POST", body={"apikey": _api_key()})
    data = json.loads(payload).get("data") or {}
    token = data.get("token")
    if not token:
        raise FlaticonError(f"Authentication returned no token: {payload[:300]!r}")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps({"token": token, "expires": time.time() + int(data.get("expires", 3600))}))
    TOKEN_CACHE.chmod(0o600)
    return token


# --------------------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------------------


def search(query: str, limit: int, shape: str | None, style: str | None, as_json: bool) -> int:
    params = {"q": query, "limit": str(limit)}
    if shape:
        params["styleShape"] = shape
    if style:
        params["styleId"] = style

    payload, _ = _request(f"{API_BASE}/search/icons/priority?{urllib.parse.urlencode(params)}", token=_token())
    items = json.loads(payload).get("data") or []

    if as_json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return 0

    if not items:
        print(f"No icon found for {query!r}. Try the singular, an English synonym, or a broader term.")
        return 1

    for item in items:
        style_name = (item.get("style") or {}).get("name") or item.get("styleName") or "?"
        style_id = (item.get("style") or {}).get("id") or item.get("styleId") or "?"
        tags = item.get("tags") or ""
        if isinstance(tags, list):
            tags = ", ".join(tags)
        print(f"{item.get('id')}\t{item.get('description', '')[:48]:<48} style={style_name}({style_id}) {tags[:60]}")
    print(f"\n{len(items)} result(s). Keep one styleId for the whole set — mixed families look wrong together.")
    return 0


# --------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------


def _download_one(icon_id: str, name: str, out_dir: Path, token: str) -> dict:
    payload, headers = _request(f"{API_BASE}/item/icon/download/{icon_id}?format=svg", token=token)

    # The endpoint may hand back the file itself, or JSON carrying a signed URL.
    content_type = (headers.get("Content-Type") or "").lower()
    if "json" in content_type:
        url = (json.loads(payload).get("data") or {}).get("url")
        if not url:
            raise FlaticonError(f"No download URL in the response for icon {icon_id}: {payload[:200]!r}")
        payload, _ = _request(url)

    if not payload.lstrip().startswith((b"<svg", b"<?xml")):
        raise FlaticonError(f"Icon {icon_id} did not come back as SVG (got {payload[:60]!r}).")

    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / f"{name}.svg"
    destination.write_bytes(payload)

    detail: dict = {}
    try:
        info, _ = _request(f"{API_BASE}/item/icon/{icon_id}", token=token)
        detail = json.loads(info).get("data") or {}
    except FlaticonError:
        # Metadata is a nicety; a missing author must not fail an otherwise good download.
        pass

    return {
        "name": name,
        "id": icon_id,
        "file": destination.name,
        "author": (detail.get("author") or {}).get("name"),
        "url": detail.get("url") or f"https://www.flaticon.com/free-icon/{icon_id}",
    }


def _record_attribution(out_dir: Path, entries: list[dict]) -> None:
    """The only record of where each icon came from — keep it even on a premium plan."""
    path = out_dir / "attribution.json"
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = []

    by_name = {entry["name"]: entry for entry in existing}
    for entry in entries:
        by_name[entry["name"]] = entry
    path.write_text(json.dumps(sorted(by_name.values(), key=lambda e: e["name"]), indent=2, ensure_ascii=False))


def download(ids: list[tuple[str, str]], out_dir: Path, as_json: bool) -> int:
    token = _token()
    written: list[dict] = []
    failed: list[str] = []

    for index, (name, icon_id) in enumerate(ids):
        try:
            written.append(_download_one(icon_id, name, out_dir, token))
        except FlaticonError as error:
            # One bad id must not lose the icons already fetched.
            failed.append(f"{name} ({icon_id}): {error}")
        if index < len(ids) - 1:
            time.sleep(DOWNLOAD_DELAY_SECONDS)

    if written:
        _record_attribution(out_dir, written)

    if as_json:
        print(json.dumps({"written": written, "failed": failed}, indent=2, ensure_ascii=False))
    else:
        for entry in written:
            print(f"✓ {entry['file']}  (id {entry['id']}, {entry.get('author') or 'auteur inconnu'})")
        for message in failed:
            print(f"✗ {message}", file=sys.stderr)
        if written:
            print(f"\nAttribution recorded in {out_dir / 'attribution.json'}")
    return 1 if failed and not written else 0


# --------------------------------------------------------------------------------------
# Inline
# --------------------------------------------------------------------------------------

_SVG_OPEN = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SVG_CLOSE = re.compile(r"</svg\s*>", re.IGNORECASE)
_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]+)"', re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FILL_ATTR = re.compile(r'\sfill\s*=\s*"(?!none)[^"]*"', re.IGNORECASE)
_STROKE_ATTR = re.compile(r'\sstroke\s*=\s*"(?!none)[^"]*"', re.IGNORECASE)
_STYLE_BLOCK = re.compile(r"<style\b.*?</style\s*>", re.IGNORECASE | re.DOTALL)


def inline(path: Path, size: float, as_json: bool) -> int:
    """Strip a Flaticon SVG down to inner markup on a `size`×`size` viewBox, in `currentColor`.

    Flaticon ships full documents with literal colours; pasted as-is into a themed component they
    render as a black square in dark mode. This removes the wrapper, drops the hardcoded fills so
    the icon inherits its surroundings, and scales the artwork to the target box.
    """
    source = path.read_text()

    open_match = _SVG_OPEN.search(source)
    if not open_match:
        raise FlaticonError(f"{path} does not look like an SVG (no <svg> element).")

    inner = source[open_match.end() :]
    close_match = _SVG_CLOSE.search(inner)
    if close_match:
        inner = inner[: close_match.start()]

    inner = _COMMENT.sub("", inner)
    if _STYLE_BLOCK.search(inner):
        # A <style> block sets colours by class, which the attribute stripping below cannot reach.
        print(
            f"warning: {path.name} carries a <style> block — check its colours render in both themes.",
            file=sys.stderr,
        )
    inner = _FILL_ATTR.sub(' fill="currentColor"', inner)
    inner = _STROKE_ATTR.sub(' stroke="currentColor"', inner)
    inner = "\n".join(line.rstrip() for line in inner.splitlines() if line.strip())

    view_box = _VIEWBOX.search(open_match.group(0))
    transform = ""
    if view_box:
        parts = [float(value) for value in re.split(r"[\s,]+", view_box.group(1).strip())]
        if len(parts) == 4:
            min_x, min_y, width, height = parts
            scale = size / max(width, height) if max(width, height) else 1
            if abs(scale - 1) > 1e-6 or min_x or min_y:
                # Centre the artwork in the target box rather than pinning it to a corner.
                offset_x = (size - width * scale) / 2 - min_x * scale
                offset_y = (size - height * scale) / 2 - min_y * scale
                transform = f'<g transform="translate({offset_x:.3f} {offset_y:.3f}) scale({scale:.5f})">'

    body = f"{transform}\n{inner}\n</g>" if transform else inner
    result = {"viewBox": f"0 0 {size:g} {size:g}", "inner": body}

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f'<!-- viewBox="0 0 {size:g} {size:g}" fill="currentColor" -->')
        print(body)
    return 0


# --------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Search, download and normalise Flaticon SVG icons.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    search_parser = sub.add_parser("search", help="search icons")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--shape", choices=["outline", "fill", "lineal-color", "hand-drawn"])
    search_parser.add_argument("--style", help="styleId — pass the same one for a consistent set")

    download_parser = sub.add_parser("download", help="download one icon")
    download_parser.add_argument("icon_id")
    download_parser.add_argument("--name", required=True, help="file name without extension")
    download_parser.add_argument("--out", type=Path, required=True)

    many_parser = sub.add_parser("download-many", help="download several icons")
    many_parser.add_argument("--id", action="append", required=True, metavar="NAME:ID")
    many_parser.add_argument("--out", type=Path, required=True)

    inline_parser = sub.add_parser("inline", help="normalise an SVG to inner markup")
    inline_parser.add_argument("file", type=Path)
    inline_parser.add_argument("--size", type=float, default=24)

    args = parser.parse_args()

    try:
        if args.command == "search":
            return search(args.query, args.limit, args.shape, args.style, args.json)
        if args.command == "download":
            return download([(args.name, args.icon_id)], args.out, args.json)
        if args.command == "download-many":
            pairs = []
            for raw in args.id:
                if ":" not in raw:
                    raise FlaticonError(f"--id expects NAME:ID, got {raw!r}")
                name, _, icon_id = raw.partition(":")
                pairs.append((name, icon_id))
            return download(pairs, args.out, args.json)
        if args.command == "inline":
            return inline(args.file, args.size, args.json)
    except FlaticonError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
