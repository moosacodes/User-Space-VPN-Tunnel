#!/usr/bin/env bash
# Bring up a local two-namespace demo and leave it running until Ctrl-C.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/scripts/bench_netns.sh" "${1:-15}" 20 10000
