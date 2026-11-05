---
name: local-fleet
description: Answer questions about the user's local inference fleet (DGX Spark / Ollama / vLLM boxes) and where Hermes is routed, using the local-fleet tools and commands.
---

# Local Fleet

The user runs local-fleet, which routes Hermes's primary model across their own inference boxes and falls back to cloud.

- "Which box am I on / is X up / why am I on cloud?" → call `fleet_status` and answer from `applied_now`, `would_route_to`, `reason` and each node's `last_health`.
- "List my boxes" → `fleet_list_nodes` (no probing).
- "Put model M on box X" → confirm size and box with the user first, then `fleet_pull_model`. Only Ollama boxes.
- Changing routing is the user's call. Tell them the command instead of doing it: `/fleet use best`, `/fleet use <box>`, `/fleet mode prefer-local|prefer-cloud|auto`, or `hermes fleet restore` to undo everything.
- Never try to run commands on a box; there is no tool for it by design.
