#!/bin/sh
# Starts (or restarts) the FlareSolverr the backend falls back on for Cloudflare challenges, and
# waits until it answers. Usage: flaresolverr.sh [start|stop]
set -eu
name=brickseeker-flaresolverr
image=ghcr.io/flaresolverr/flaresolverr:v3.5.2

if [ "${1:-start}" = stop ]; then
  docker rm -f "$name"
  exit 0
fi

docker info >/dev/null 2>&1 || { echo "Docker ne répond pas : lance Docker Desktop." >&2; exit 1; }

docker rm -f "$name" >/dev/null 2>&1 || true
# Same settings as docker-compose.yml's `flaresolverr` service, minus its network.
docker run -d --name "$name" --restart unless-stopped --shm-size 1gb \
  -e LOG_LEVEL=info -p 127.0.0.1:8191:8191 "$image" >/dev/null

for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8191/health >/dev/null 2>&1; then
    echo "FlareSolverr prêt sur http://localhost:8191"
    exit 0
  fi
  sleep 1
done
echo "FlareSolverr n'a pas répondu en 60 s (docker logs $name)." >&2
exit 1
