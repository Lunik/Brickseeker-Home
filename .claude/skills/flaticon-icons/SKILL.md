---
name: flaticon-icons
description: Search, download and install SVG icons from Flaticon into a project's icon set. Use when the user asks for Flaticon icons, wants to replace emoji or placeholder icons with real ones, needs a new icon added to an existing set, or mentions flaticon.com. Requires a Flaticon API key.
---

# Flaticon icons

Pull real SVG icons from Flaticon's API and install them into a project's icon set.

## Before anything: the API key

Every call needs a key from <https://developers.flaticon.com/> (Flaticon account → API →
create a project). The scripts read it from `FLATICON_API_KEY`, falling back to
`~/.config/flaticon/api_key`.

```bash
mkdir -p ~/.config/flaticon && printf '%s' 'YOUR_KEY' > ~/.config/flaticon/api_key && chmod 600 ~/.config/flaticon/api_key
```

**Never commit the key, and never paste it into a file inside the repository.** If the user offers
it in chat, write it to the path above and use it from there.

## Licence and attribution — check this before shipping

Flaticon's tiers differ, and this decides whether the project needs an attribution line:

- **Free tier** — attribution is *required* wherever the icons appear. Record it.
- **Premium / paid** — no attribution required.

`download.py` always writes an `attribution.json` next to the icons recording each icon's id,
author and Flaticon URL. Keep it even on a premium plan: it is the only record of where an icon
came from, which matters when the licence is audited or the plan changes.

Do not redistribute the raw SVGs as a standalone icon pack — that is outside every Flaticon
licence. Using them inside an application is what the licence covers.

## Workflow

### 1. Search

```bash
python3 scripts/flaticon.py search "shopping cart" --limit 20 --shape outline
```

Prints `id`, description, style and tags. `--shape` takes `outline`, `fill`, `lineal-color`,
`hand-drawn`; `--style` takes a numeric style id when you want every icon from one family.

**Pick one family and stay in it.** An icon set assembled from several styles reads as a jumble —
mixed stroke weights and corner radii are obvious next to each other even when each icon is fine
alone. Search once, note the `styleId` of an icon you like, then pass `--style <id>` for every
subsequent icon so the whole set matches.

### 2. Download

```bash
python3 scripts/flaticon.py download 12345 --name search --out frontend/src/assets/icons
```

Writes `search.svg` and appends to `attribution.json`. Downloads several at once with repeated
`--id NAME:ID` pairs:

```bash
python3 scripts/flaticon.py download-many --out frontend/src/assets/icons \
  --id home:1234 --id box:5678 --id camera:9012
```

### 3. Install into the project's icon set

How depends on what the project already has. Check before writing:

- **An existing `Icon` component with a path map** (the common case): each Flaticon SVG is a
  full document, so extract its drawable content rather than pasting the whole file. Run
  `python3 scripts/flaticon.py inline <file.svg>` to get the inner markup normalised to a
  24×24 viewBox with `fill="currentColor"`, then paste that into the component's map.
- **No icon component yet**: import the `.svg` files directly — Vite, Next and CRA all handle
  `import icon from './icon.svg'` — or build a small component that inlines them.

**Prefer `currentColor` over a hardcoded fill.** Flaticon's SVGs ship with literal colours; the
`inline` command strips them so the icon inherits the surrounding text colour and therefore works
in both light and dark themes. Keep a literal colour only when the icon is deliberately
multi-colour (a brand mark, a flag).

### 4. Verify

Render the app and look at the icons together, at their real size. The failure modes are visual
and do not show up in a build:

- an icon whose stroke weight is heavier than its neighbours (wrong family);
- an icon that vanishes in dark mode (a literal `fill="#000"` survived);
- an icon whose artwork touches the viewBox edge, so it looks larger than the others.

## Scripts

| Command | Purpose |
|---|---|
| `flaticon.py search QUERY` | Search icons; prints ids, styles and tags |
| `flaticon.py download ID` | Download one SVG by id |
| `flaticon.py download-many` | Download several, `--id name:id` per icon |
| `flaticon.py inline FILE` | Normalise an SVG to 24×24 `currentColor` inner markup |

All commands accept `--json` for machine-readable output.

## Notes

- The auth token is short-lived; the script fetches a fresh one per run and caches it in
  `~/.config/flaticon/token.json`. A 401 mid-run means the token expired — rerun.
- Rate limits apply per plan. `download-many` spaces its requests; do not parallelise it.
- Search results are ranked, not exhaustive. If nothing fits, try the singular form, an English
  synonym, or a broader term — Flaticon's index is English-only.
