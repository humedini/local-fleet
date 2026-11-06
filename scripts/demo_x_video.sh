#!/usr/bin/env bash
# A 90-120 s demo of Local Fleet, one beat per Enter, for a screen recording. Use a dedicated Hermes
# profile so no real chats appear, and hide addresses:
#   hermes profile create demo && ln -s "$PWD" ~/.hermes/profiles/demo/plugins/local-fleet
#   hermes -p demo plugins enable local-fleet
#   BOX1=http://10.0.0.21:11434/v1 BOX2=http://10.0.0.22:11434/v1 BOX3=http://10.0.0.30:11434/v1 \
#   MODEL=gpt-oss:120b FALLBACK=qwen3:14b scripts/demo_x_video.sh
# The failover beats use rehearsals: simulated outages inside Local Fleet only. Nothing is stopped on
# any box, so the demo is safe to repeat. Keep the Desktop's Local Fleet page beside the terminal.
set -euo pipefail
: "${BOX1:?base URL of box 1}" "${BOX2:?base URL of box 2}" "${BOX3:=}"
: "${MODEL:=gpt-oss:120b}" "${FALLBACK:=qwen3:14b}"
: "${CLOUD_PROVIDER:=openrouter}" "${CLOUD_MODEL:=anthropic/claude-sonnet-4}"
H="hermes -p ${PROFILE:-demo}"
BOXES="box1 box2${BOX3:+ box3}"

beat() { printf '\n\033[1;32m# %s\033[0m\n' "$1"; read -r -p "" _; }
# Echo each command with any URL replaced, so addresses never reach the recording.
run() { printf '\033[2m$ %s\033[0m\n' "$(printf '%s ' "$@" | sed -E 's#https?://[^ ]+#<address>#g')"; "$@"; }

beat "1. Register the boxes (addresses hidden on screen)"
run $H fleet privacy on
run $H fleet add --name box1 --url "$BOX1" --kind ollama
run $H fleet add --name box2 --url "$BOX2" --kind ollama
[ -n "$BOX3" ] && run $H fleet add --name box3 --url "$BOX3" --kind ollama
run $H fleet model "$MODEL" --fallback "$FALLBACK"
run $H fleet cloud "$CLOUD_PROVIDER" "$CLOUD_MODEL"
run $H fleet price 3 15 --currency GBP

beat "2. Hermes moves to the least busy box. Why that one?"
run $H fleet use --best
run $H fleet why

beat "3. Rehearse an outage on the box Hermes is on (nothing is stopped on it)"
run $H fleet rehearse box1 --minutes 10

beat "4. Rehearse the rest: no local box left, so cloud takes over"
for b in $BOXES; do [ "$b" = box1 ] || run $H fleet rehearse "$b" --minutes 10; done

beat "5. End the rehearsal on box 1: Hermes comes back to it"
run $H fleet rehearse box1 --stop

beat "6. The flight recorder: configured routes, what actually served, the rehearsals"
run $H fleet events -n 12

beat "7. What did running locally save? The working, not just a number"
run $H fleet stats

beat "8. Fleet doctor, then tidy up the rehearsals"
run $H fleet doctor || true
for b in $BOXES; do run $H fleet rehearse "$b" --stop >/dev/null; done
printf '\n\033[1;32m# Local Fleet: your local inference fleet, operated from Hermes Desktop  @NousResearch\033[0m\n'
