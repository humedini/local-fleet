#!/usr/bin/env bash
# Render README / catalog images from synthetic data (make_demo_state.py): the page, the chip panel
# and an animated GIF of the live map. Needs google-chrome and ffmpeg; React comes from esm.sh.
set -euo pipefail
cd "$(dirname "$0")"
OUT=../../docs/img
FFMPEG=${FFMPEG:-ffmpeg}
python3 make_demo_state.py
cp ../../desktop/plugin.js plugin.js
python3 -m http.server 8766 --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER; rm -f plugin.js; rm -rf frames' EXIT
sleep 1
shot() { google-chrome --headless=new --disable-gpu --hide-scrollbars --window-size="$2" --virtual-time-budget="${4:-6000}" \
  --screenshot="$3" "http://127.0.0.1:8766/index.html?view=$1" 2>/dev/null; }
shot page 1440,1500 "$OUT/fleet-page.png"
shot chip 412,480 "$OUT/fleet-chip.png"
mkdir -p frames
for i in $(seq 0 23); do shot page 1440,900 "frames/f$(printf %02d "$i").png" $((4000 + i * 75)); done
"$FFMPEG" -loglevel error -y -framerate 12 -i frames/f%02d.png \
  -vf "crop=1440:700:0:185,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse" \
  "$OUT/fleet-map.gif"
ls -la "$OUT"
