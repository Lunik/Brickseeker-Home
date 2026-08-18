---
name: scanner-sheet-checklist
description: Checklist for adding any sheet, overlay, toggle or text input to ScannerPage (the full-screen camera route). Use whenever you add a new `<Sheet>`, dialog, picker or presented flag to ScannerPage, or anything that changes the OCR loop, the scan feedback or the mode-lot session.
---

# Adding a surface to ScannerPage

`frontend/src/pages/ScannerPage.tsx` is a live camera plus an OCR poll loop, with sheets stacked
over it (ambiguous set, manual entry) and a route it navigates away to (mode lot summary). Every
addition here has hit the same handful of gotchas.

## 1. Anything covering the camera goes into `isCovered`

`isCovered` is the single source of truth: it feeds `useCamera(!isCovered)`, which stops the
`MediaStream` tracks, *and* it early-returns the capture `setInterval`. A sheet that isn't in that
chain leaves the camera light on behind it, keeps uploading frames to `/scan/ocr`, and can yank the
user off a half-typed form by navigating to a set that resolved in the background.

```bash
grep -n "useState\|isCovered" frontend/src/pages/ScannerPage.tsx
```

Every presented flag in that list must appear on the `isCovered` line unless it demonstrably does
not cover the video (`batchMode`, `candidate`, `message` don't). Never add a second `useEffect`
that starts/stops the camera — it will fight `useCamera` over the same tracks.

## 2. One capture loop, and it must not fire during a lookup

`inFlightRef` (an OCR round-trip is out) and `resolvingRef` (a `/scan/lookup` is out) both gate the
interval. They are refs, not state, on purpose: putting `resolving` in the effect deps tore the
timer down and rebuilt it on every resolve, restarting the 800 ms cadence each time. If your surface
needs the loop paused for a reason that is not "the camera is covered", add a ref guard inside the
interval — don't add it to the effect's dependency array.

## 3. Text input — focused on open

The keyboard should be up when the sheet appears; `<Sheet>` does not do this for you. The manual
entry input carries `autoFocus` (and `inputMode="numeric"`), which is the whole pattern — copy it.

## 4. Feedback is the camera path only

`lib/feedback.ts` (sound + vibration together, the port of `ScanFeedback.swift`) exists because the
phone is at arm's length pointed at a shelf. A lookup the user typed themselves must stay silent:

```bash
grep -rn "playCandidateDetected\|playResolutionSucceeded\|playResolutionFailed" frontend/src | grep -v lib/feedback.ts
```

Every hit in `resolve()` is guarded by `withFeedback` (`source === 'camera'`); the detection beep
sits inside the capture loop, which only runs on the camera path. Two rules the iOS version paid
for: the detection cue fires at detection, before any network call, so the user knows the shot
landed — and it fires **once** per candidate, deduped by `pulsedRef`, because the loop re-sees the
same number every ~800 ms. Any new call site needs both the source guard and a dedupe.

## 5. State that must outlive the camera lives outside the component

The scanner is a route: opening a scanned set unmounts it. `lib/batch-session.ts` is a module-level
store with a `useSyncExternalStore` hook precisely because a session held in `useState` was
destroyed by the act of looking at anything in it. Same for the price cache. If your surface
accumulates something the user expects to still be there after visiting a set, it does not go in
`useState`.

## 6. `source` decides what the scan *means*

`/scan/lookup` records a `ScanEvent` for `camera`/`manualEntry`/`photoImport` but stores coordinates
only for `camera` — a typed number says nothing about where you were standing. Pass the honest
source from your surface; don't reuse `'camera'` to get the Historique row.

## 7. Mutations must invalidate, not just set local state

There is no shared view model here: Historique, Collection and Statistiques are React Query caches.
`resolve()` invalidates `['history']` after a successful lookup. If your surface changes collection
or list membership, invalidate the affected keys (`['history']`, `['collection']`, `['set', setNum]`,
`['stats']`) — or use `hooks/useSetActions.ts`, which already does. *(This replaces the iOS
`LocalRepository.cacheSet` re-sync; the mechanism differs, the failure — a stale list behind the
sheet — is identical.)*

## 8. Check it compiles

```bash
cd frontend && npx tsc -b --noEmit && npm run build
```

Both pass clean today, so any error is yours. Note that neither this nor any test proves items 1–2:
the camera stopping and the loop pausing are only observable in a real browser over HTTPS
(`getUserMedia` is refused on a plain-HTTP LAN address). Open the sheet and confirm the camera
indicator goes out, and that `/scan/ocr` requests stop in the network panel.
