#!/usr/bin/env bash
# Catalog storyboard: three frames of the Local Fleet page from the invented fleet in
# make_demo_state.py (no real names, addresses or traffic): 1 local, 2 a simulated cloud hop (a
# rehearsal pack), 3 recovered. Each frame is stamped with the plugin version and the commit it was
# rendered from. Needs google-chrome; React comes from esm.sh. Writes docs/img/storyboard-*.png.
set -euo pipefail
cd "$(dirname "$0")"
OUT=../../docs/img
VERSION=$(sed -n 's/^version: *//p' ../../plugin.yaml)
SHA=$(git -C ../.. rev-parse --short HEAD)
python3 make_demo_state.py >/dev/null
cp ../../desktop/plugin.js plugin.js
python3 -m http.server 8768 --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER; rm -f plugin.js storyboard-*.json' EXIT
sleep 1
n=1
for frame in local cloud recover; do
  stamp="Local Fleet ${VERSION} · ${SHA} · ${n}/3 ${frame} · synthetic data"
  google-chrome --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --virtual-time-budget=6000 \
    --screenshot="$OUT/storyboard-${n}-${frame}.png" \
    "http://127.0.0.1:8768/index.html?view=page&state=storyboard-${frame}&stamp=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$stamp")" 2>/dev/null
  n=$((n + 1))
done
ls -la "$OUT"/storyboard-*.png
