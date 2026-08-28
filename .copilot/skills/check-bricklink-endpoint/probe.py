#!/usr/bin/env python3
"""One real, signed BrickLink Store API call — printed as a response *shape*.

Runs inside the container so it can reuse the app's own code: `sign_oauth1` from
`app.services.bricklink` (never re-derive the signature) and the four credentials from the
Fernet-encrypted `credentials` table via `app.security.get_bricklink_credentials`. Secrets are
read, used and never printed.

    docker exec -i -e PYTHONPATH=/app/backend brickseeker python - \
      --path /items/SET/10300-1/price --guide --query new_or_used=U < probe.py

`--guide` merges `PRICE_GUIDE_PARAMS` (the exact `guide_type`/`currency_code`/`region`/`vat`
the app sends) so the probe reproduces the real call instead of a lookalike. `--raw` dumps the
whole payload. Deliberately *not* routed through `BrickLinkClient.get`: that one raises on
`meta.code != 200` and hands back only `data`, whereas the envelope's `meta` is the outcome
worth seeing here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from urllib.parse import quote

import httpx

from app.db import session_scope
from app.security import get_bricklink_credentials
from app.services.bricklink import BASE_URL, PRICE_GUIDE_PARAMS, sign_oauth1


def describe(value: object, indent: int = 0, samples: int = 2) -> None:
    """Keys, types and a real value each — plus a couple of array entries as evidence."""
    pad = "  " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{pad}{key}: {type(item).__name__}")
                describe(item, indent + 1, samples)
            else:
                print(f"{pad}{key}: {type(item).__name__} = {item!r}")
    elif isinstance(value, list):
        print(f"{pad}({len(value)} entries)")
        for entry in value[:samples]:
            describe(entry, indent + 1, samples)
            print(f"{pad}  --")


async def run(path: str, query: dict[str, str], raw: bool) -> int:
    async with session_scope() as session:
        credentials = await get_bricklink_credentials(session)
    if credentials is None:
        print("BrickLink is not configured: the four OAuth values are missing from the store.")
        print("Nothing can be proven without a signed call — stop here, don't invent a shape.")
        return 2

    url = f"{BASE_URL}{path}"
    header = sign_oauth1("GET", url, query, **credentials)
    # Query string built with the encoder the signature uses (RFC 5849 §3.6, unreserved only), so
    # what is signed and what goes on the wire cannot drift — same reason `BrickLinkClient` does.
    encoded = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(query.items()))
    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.get(
            f"{url}?{encoded}" if encoded else url, headers={"Authorization": header}
        )

    print(f"HTTP {response.status_code}  GET {path}  {query}\n")
    try:
        envelope = response.json()
    except ValueError:
        print(response.text[:2000])
        return 1

    if raw:
        print(json.dumps(envelope, indent=2)[:20000])
        return 0

    # HTTP 200 is not the outcome: an auth or quota failure arrives as 200 + meta.code 401/429.
    print(json.dumps(envelope.get("meta", {}), indent=2))
    if "data" in envelope:
        print("\ndata:")
        describe(envelope["data"], indent=1)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="e.g. /items/SET/10300-1/price")
    parser.add_argument("--query", nargs="*", default=[], metavar="k=v")
    parser.add_argument("--guide", action="store_true", help="merge PRICE_GUIDE_PARAMS")
    parser.add_argument("--raw", action="store_true", help="dump the full payload")
    args = parser.parse_args()

    query = dict(PRICE_GUIDE_PARAMS) if args.guide else {}
    query.update(pair.split("=", 1) for pair in args.query)
    sys.exit(asyncio.run(run(args.path, query, args.raw)))


if __name__ == "__main__":
    main()
