#!/bin/sh
# Starts (or restarts) the Browserless Chromium the backend drives over CDP, and waits until it
# answers. Usage: chromium.sh [start|stop]
set -eu
name=brickseeker-chromium
image=ghcr.io/browserless/chromium:v2.55.4

if [ "${1:-start}" = stop ]; then
  docker rm -f "$name"
  exit 0
fi

docker info >/dev/null 2>&1 || { echo "Docker ne répond pas : lance Docker Desktop." >&2; exit 1; }

docker rm -f "$name" >/dev/null 2>&1 || true
# Same settings as docker-compose.yml's `chromium` service, minus its network; published on
# loopback only because the CDP endpoint gives full control of the browser.
docker run -d --name "$name" --restart unless-stopped --shm-size 1gb \
  -e TIMEOUT=86400000 -p 127.0.0.1:3000:3000 "$image" >/dev/null

for _ in $(seq 1 60); do
  if curl -fsS http://localhost:3000/pressure >/dev/null 2>&1; then
    echo "Chromium prêt sur ws://localhost:3000"
    exit 0
  fi
  sleep 1
done
echo "Chromium n'a pas répondu en 60 s (docker logs $name)." >&2
exit 1
