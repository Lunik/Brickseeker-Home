---
name: check-bricklink-endpoint
description: Verify the real response shape of a BrickLink Store API endpoint with one signed probe call, before implementing or trusting code against it. Use before decoding any new BrickLink field or endpoint, or when a price/mapping looks wrong and the cause isn't obvious in our code.
---

# Verifying a BrickLink Store API endpoint

BrickLink publishes **no machine-readable spec**. Its HTML reference (`bricklink.com/v3/api.page`)
is rendered client-side and returns an empty shell to any fetcher, and third-party clients encode
their authors' assumptions, not a contract. Every endpoint is OAuth 1.0a signed, so a bare `curl`
proves nothing either. The only trustworthy answer to "what does this actually return" is a real
signed call — `probe.py` makes one.

## Run the probe

It runs **inside the container**: that is where `httpx`, the app package and the credentials live.
`sign_oauth1` and `PRICE_GUIDE_PARAMS` are imported from `app.services.bricklink` — never write a
second signer, a signature that drifts from the app's returns a 401 indistinguishable from bad
credentials. The four secrets are read from the Fernet-encrypted `credentials` table via
`get_bricklink_credentials` and never printed.

```bash
docker exec -i -e PYTHONPATH=/app/backend brickseeker python - \
  --path /items/SET/10300-1/price --guide --query new_or_used=U \
  < .claude/skills/check-bricklink-endpoint/probe.py
```

`PYTHONPATH` is required: `pip install ./backend` only installed the package stub, the real code is
under `/app/backend` (which is why the CMD passes `--app-dir`). `--guide` merges the app's exact
`guide_type`/`currency_code`/`region`/`vat`; without it you are probing a different market than the
one we store. `--raw` dumps the whole payload. If BrickLink isn't configured the script says so and
exits — stop there rather than inventing a shape.

Pick an item that will have data: a popular long-retired set (`10300-1`) has real sales, an obscure
or brand-new one legitimately returns zeros, which proves nothing. `region=europe` shrinks samples
hard — `10300-1` used came back with **4** sales.

Record what you saw where the decoder lives (`services/bricklink.py` docstrings,
`docs/contract.md`), like the notes already there. That is the evidence the fields were seen, not
assumed.

## Before writing code against what you found

- **HTTP 200 is not the outcome.** Auth and quota failures arrive as HTTP 200 with `meta.code`
  401/429. The probe prints `meta` first for that reason; `BrickLinkClient` is the only thing that
  may hide it.
- **Prices are decimal strings, quantities are ints** — verified live: `avg_price: '118.7375'`,
  `unit_quantity: 4`. Don't decode a price as a number.
- **Present-but-zero means absent.** An item with no sale in the window returns `"0.0000"` rather
  than omitting the field (`_positive` exists for this).
- **Decode leniently.** `price_detail[]` rows carry a `qunatity` field next to `quantity` —
  BrickLink's own typo, live today. A strict decoder throws the whole payload away over junk like
  that and costs us the price we display; everything past `avg_price` is decoration.
- **One item at one moment is not a contract.** A field present once is not always present, and
  `price_detail[]` is empty for an item with no sales.
- **`guide_type` and `region` change the meaning, not just the numbers.** `sold` is realised sales,
  `stock` is current asking prices; the repo also records that `region=BOGUS` returns 200 and
  silently reverts to a worldwide average while `vat=BOGUS` returns 400 — a typo there fails open.
  Probing with different values is fine; changing `PRICE_GUIDE_PARAMS` redefines every stored
  history point and deal verdict.

Dropped from the iOS version: the four `BL_*` environment variables (credentials come from the
encrypted store here — re-exporting them would be a second copy to leak) and its stdlib-only
constraint (the container already has `httpx` and the app's own signer, which is the point).
