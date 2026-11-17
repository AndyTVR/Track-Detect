#!/bin/sh
# Run every automated test: the server tests, then the page in a browser.
# TD_TESTDATA: folder of test recordings (see README.md).
set -e
cd "$(dirname "$0")/.."
TESTDATA="${TD_TESTDATA:-/home/claude/td-testdata}"
python3 -m pytest tests -q
TMP=$(mktemp -d)
mkdir -p "$TMP/data" "$TMP/rec"
for f in "$TESTDATA"/*.ats; do ln -s "$(readlink -f "$f")" "$TMP/rec/$(basename "$f")"; done
TD_DATA="$TMP/data" python3 app.py --port 8897 --no-browser > "$TMP/server.log" 2>&1 &
PID=$!
sleep 4
node tests/ui_smoke.js http://127.0.0.1:8897 "$TMP/rec" "$TMP" || { kill $PID; echo "server log: $TMP/server.log"; exit 1; }
kill $PID
rm -rf "$TMP"
