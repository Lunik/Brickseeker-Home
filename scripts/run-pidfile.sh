#!/bin/sh
# Usage: run-pidfile.sh <name> <match> <command...>
# Kills the previous instance recorded for <name> (if still running and its command line contains
# <match>, so a recycled PID is never hit), records the new PID in $TMPDIR, then exec's the command.
set -eu
name=$1 match=$2
shift 2
dir="${TMPDIR:-/tmp}/brickseeker-pids"
pidfile="$dir/$name.pid"
mkdir -p "$dir"

if [ -f "$pidfile" ]; then
  old=$(cat "$pidfile")
  if [ -n "$old" ] && ps -p "$old" -o command= 2>/dev/null | grep -q -- "$match"; then
    echo "[$name] arrêt de l'instance précédente (pid $old)"
    kill "$old" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$old" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$old" 2>/dev/null || true
  fi
  rm -f "$pidfile"
fi

echo $$ > "$pidfile"
exec "$@"
