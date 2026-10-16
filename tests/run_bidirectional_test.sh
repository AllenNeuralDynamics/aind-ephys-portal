#!/usr/bin/env bash
# Usage: tests/run_bidirectional_test.sh [num_iframes]  (default 1)
# Start the ephys GUI server (5006) and the bidirectional test app (5007); Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

python entrypoint.py --port 5006 --address localhost &
trap 'kill 0' EXIT

panel serve tests/test_bidirectional_communication.py --port 5007 --allow-websocket-origin="*" --show --args --num-iframes "${1:-1}"
