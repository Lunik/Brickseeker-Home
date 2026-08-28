---
name: check-rebrickable-endpoint
description: Verify the real request/response shape of a Rebrickable API v3 endpoint against the live API before implementing or trusting code against it. Use before adding or changing any RebrickableClient method or `from_payload`, and when "Erreur lors du traitement de la réponse" (502) shows up without an obvious cause.
---

# Verifying a Rebrickable API endpoint

`https://rebrickable.com/api/v3/swagger/?format=openapi` lists every path but **omits response
schemas and most form-body details** — every path reads `"responses": {"200": {"description": ""}}`
and nothing else. It tells you an endpoint exists, never what it returns. That gap already cost the
iOS app two production bugs, and both are ported into `services/rebrickable.py` as comments.

## Probe the live endpoint

The container mounts `./data`, so it has the real encrypted credentials. `client_for` decrypts them
and `_get` runs the same throttle + `Authorization` header the app uses:

```bash
docker compose exec -T --workdir /app/backend brickseeker python - <<'PY'
import asyncio, json
from app.db import session_scope
from app.services.rebrickable import client_for

PATH = "/lego/sets/10307-1/minifigs/"
PARAMS = {"page_size": "1"}

async def main():
    async with session_scope() as session:
        client = await client_for(session)
        print(json.dumps(await client._get(PATH, PARAMS), indent=2, ensure_ascii=False)[:4000])

asyncio.run(main())
PY
```

**Never print the key.** The recipe above never has it in a variable you can echo — keep it that
way. No `echo $BRICKSEEKER_SECRET_KEY`, no dumping the `Credential` row, no pasting a key into a
throwaway `curl`; a key in scrollback is a key in the transcript.

Two things that will waste a call if you skip them:

- Probe **read** endpoints only from here. A `POST`/`PATCH`/`DELETE` probe mutates the user's real
  collection, and there is no separate test account.
- Pick a target you know is populated. The run above returned `{"count": 0, ..., "results": []}` —
  10307-1 has no minifigs. That proves the plumbing, and tells you nothing about item shape.

To check credentials/imports without spending an HTTP call, replace the body with
`print(bool(client._api_key), bool(client._user_token))` — `client_for` touches only SQLite.

## Cross-check the community spec

Same backend, fuller parameter prose (still no response schemas):

```bash
git clone --depth 1 https://github.com/rienafairefr/pyrebrickable.git /tmp/pyrebrickable_check
grep -n '"/api/v3/users/{user_token}/sets/{set_num}/' /tmp/pyrebrickable_check/rebrickable.json
sed -n '<line>,<line+100>p' /tmp/pyrebrickable_check/rebrickable.json
```

Read the `description` field — it is prose, but it is often the only place the truth appears. That
one says `list_id` and `include_spares` "may not be accurate unless the Set actually only exists in
a single Set List", which is why `fetch_all_user_sets` dedupes by `set_num`.

## Rules that still bite here

- **Nested payloads.** `GET /users/{token}/sets/{set_num}/` returns the set under a `"set"` key, and
  the flag is `include_spares`, not `inc_spares`. Get the exact keys before writing `from_payload` —
  guessing is what caused the original bug.
- **The two pivot endpoints are not symmetric.** `/lego/sets/{n}/minifigs/` sends the name as
  `set_name` and no `num_parts`/`set_url`; `/lego/minifigs/{n}/sets/` sends the opposite. Verify
  each direction separately, however obvious the mirror looks.
- **`list_id` is a path segment, not a body field.** `POST /users/{token}/sets/` silently ignores it;
  targeting a list means `POST /users/{token}/setlists/{list_id}/sets/`.
- **Write endpoints: check the status, never decode the body.** `_request` already raises on a bad
  status. `add_set_to_list` / `move_set_to_list` / `update_set_quantity` deliberately drop the
  response and re-read via `fetch_user_set`; decoding it failed on adds that had already succeeded.
- **Don't assume capabilities that "should" exist.** `setlists` are lists of sets the user *owns* —
  there is no generic wishlist API. A wishlist was built on that assumption and reverted; the gift
  list lives on Brickset. Read the full `description` before building on an endpoint's implied
  semantics.

## After you find the real shape

A shape change is a contract change: update `docs/contract.md` and the code on both sides in the
same change, never one without the other.

Dropped from the iOS version: the "no test target, verify by hand" clause. `backend/tests/` exists,
but nothing in it hits the network, so it still cannot catch a wrong `from_payload` — the probe
above is the verification, not `pytest`. Also dropped: `CollectionStatus.unknown` as a symptom.
Here a bad shape raises `_decoding_error()` → HTTP 502 "Erreur lors du traitement de la réponse";
that message means "Rebrickable's shape moved", never a network or auth problem.
