---
name: spark-fleet
description: Answer questions about the user's local inference fleet (Spark / Ollama / vLLM boxes) and where Hermes is routed, using the hermes-spark tools and commands.
---

# Spark fleet

The user runs hermes-spark, which routes Hermes's primary model across their own inference boxes and falls back to cloud.

- "Which box am I on / is X up / why am I on cloud?" → call `spark_status` and answer from `applied_now`, `would_route_to`, `reason` and each node's `last_health`.
- "List my boxes" → `spark_list_nodes` (no probing).
- "Put model M on box X" → confirm size and box with the user first, then `spark_pull_model`. Only Ollama boxes.
- Changing routing is the user's call. Tell them the command instead of doing it: `/spark use freest`, `/spark use <box>`, `/spark mode prefer-local|prefer-cloud|auto`, or `hermes spark restore` to undo everything.
- Never try to run commands on a box; there is no tool for it by design.
