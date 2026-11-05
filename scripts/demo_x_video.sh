#!/usr/bin/env bash
# A 90-120 s demo of Local Fleet, one beat per Enter, for a screen recording. Use a dedicated Hermes
# profile so no real chats appear, and hide addresses:
#   hermes profile create demo && ln -s "$PWD" ~/.hermes/profiles/demo/plugins/local-fleet
#   hermes -p demo plugins enable local-fleet
#   BOX1=http://10.0.0.21:11434/v1 BOX2=http://10.0.0.22:11434/v1 BOX3=http://10.0.0.30:11434/v1 \
#   MODEL=gpt-oss:120b FALLBACK=qwen3:14b scripts/demo_x_video.sh
# Beats 5-6 need you to stop and restart Ollama on box 1 (and box 2) in another terminal.
set -euo pipefail
: "${BOX1:?base URL of box 1}" "${BOX2:?base URL of box 2}" "${BOX3:=}"
: "${MODEL:=gpt-oss:120b}" "${FALLBACK:=qwen3:14b}"
: "${CLOUD_PROVIDER:=openrouter}" "${CLOUD_MODEL:=anthropic/claude-sonnet-4}"
H="hermes -p ${PROFILE:-demo}"

beat() { printf '\n\033[1;32m# %s\033[0m\n' "$1"; read -r -p "" _; }
run() { printf '\033[2m$ %s\033[0m\n' "$*"; "$@"; }

beat "1. Register the boxes (addresses hidden on screen)"
run $H fleet privacy on
run $H fleet add --name box1 --url "$BOX1" --kind ollama
run $H fleet add --name box2 --url "$BOX2" --kind ollama
[ -n "$BOX3" ] && run $H fleet add --name box3 --url "$BOX3" --kind ollama
run $H fleet model "$MODEL" --fallback "$FALLBACK"
run $H fleet cloud "$CLOUD_PROVIDER" "$CLOUD_MODEL"

beat "2. Live health, memory and speed"
run $H fleet status
run $H fleet bench

beat "3. Hermes moves to the least busy box, and stays loaded"
run $H fleet keep on
run $H fleet use --best

beat "4. Subagents across the fleet (then ask Hermes for parallel research in the Desktop)"
run $H fleet delegate on

beat "5. Stop Ollama on box 1 now; the watch moves Hermes (Ctrl-C when the story is told)"
run $H fleet watch --interval 5 || true

beat "6. Real traffic, local share, spend avoided"
run $H fleet price 3 15 --currency GBP
run $H fleet stats

beat "7. Readiness, and everything is undoable"
run $H fleet doctor || true
printf '\n\033[1;32m# Local Fleet: github.com/humedini/local-fleet  @NousResearch\033[0m\n'
