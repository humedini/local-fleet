#!/usr/bin/env bash
# The 90-120 s X demo, one beat per Enter. Run it in a large-font terminal in a throwaway
# HERMES_HOME so the recording shows a clean fleet:
#   export HERMES_HOME=$(mktemp -d); mkdir -p $HERMES_HOME/plugins
#   ln -s "$PWD" $HERMES_HOME/plugins/local-fleet && hermes plugins enable local-fleet
#   SPARK1=http://192.168.1.50:11434/v1 SPARK2=http://192.168.1.51:11434/v1 \
#   CLOUD_PROVIDER=openrouter CLOUD_MODEL=anthropic/claude-sonnet-4 MODEL=qwen3.6:35b-a3b scripts/demo_x_video.sh
# Beat 4 needs SPARK1 to go down: stop Ollama on that box when prompted (or pull its cable).
set -euo pipefail
: "${SPARK1:?base URL of box 1}" "${SPARK2:?base URL of box 2}"
: "${CLOUD_PROVIDER:=openrouter}" "${CLOUD_MODEL:=anthropic/claude-sonnet-4}" "${MODEL:=}"

beat() { printf '\n\033[1;32m# %s\033[0m\n' "$1"; read -r -p "" _; }
run() { printf '\033[2m$ %s\033[0m\n' "$*"; "$@"; }

beat "1. Two Spark-class boxes, one plugin"
run hermes fleet add --name spark1 --url "$SPARK1" --kind ollama --label lan
run hermes fleet add --name spark2 --url "$SPARK2" --kind ollama --label lan
run hermes fleet cloud "$CLOUD_PROVIDER" "$CLOUD_MODEL"
[ -n "$MODEL" ] && run hermes fleet model "$MODEL"

beat "2. Live health and load"
run hermes fleet status

beat "3. auto: route to the freest healthy box"
run hermes fleet mode auto

beat "4. Stop Ollama on spark1 now, then press Enter (watch fails over / moves boxes)"
run hermes fleet watch --interval 5 &
WATCH=$!
beat "5. Start Ollama on spark1 again, press Enter once watch shows the failback"
kill "$WATCH" 2>/dev/null || true

beat "6. In chat: /fleet status — and the Desktop chip (switch to the Desktop window now)"
run hermes chat -q "/fleet status" -Q || true

beat "7. Doctor, and everything is undoable"
run hermes fleet doctor
run hermes fleet restore
printf '\n\033[1;32m# local-fleet — github.com/humedini/local-fleet  @NousResearch\033[0m\n'
