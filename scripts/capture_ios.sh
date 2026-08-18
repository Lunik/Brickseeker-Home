#!/usr/bin/env bash
# Capture one iOS screen from the booted simulator.
#
#   scripts/capture_ios.sh 01-accueil
#
# Navigation is deliberately NOT automated: the iOS app has no deep links for most screens, so
# driving it means a brittle chain of taps at hardcoded coordinates that breaks the moment a row
# height changes. Navigate by hand (or with the simulator MCP's tap), then run this to save the
# frame. `xcrun simctl` writes straight to disk, so a capture costs nothing to review later.
set -euo pipefail

NAME="${1:-}"
OUT_DIR="${2:-docs/ui-parity/ios}"
UDID="${BRICKSEEKER_SIM_UDID:-$(xcrun simctl list devices booted -j \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["devices"]; print(next((x["udid"] for v in d.values() for x in v), ""))')}"

if [ -z "$NAME" ]; then
  echo "usage: scripts/capture_ios.sh <name> [out-dir]" >&2
  echo "  e.g. scripts/capture_ios.sh 01-accueil" >&2
  exit 2
fi

if [ -z "$UDID" ]; then
  echo "Aucun simulateur démarré. Lancez-en un : xcrun simctl boot <device>" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
xcrun simctl io "$UDID" screenshot --type=png "$OUT_DIR/$NAME.png" >/dev/null 2>&1
echo "✓ $OUT_DIR/$NAME.png"
