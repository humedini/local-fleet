# Catalog listing copy

## Short (≤200 chars)

Route Hermes across your Spark / Ollama boxes: health probes, freest-box pick, prefer-local / cloud / auto, cloud failover and failback, Desktop chip + /spark.

## Long

**hermes-spark** connects Hermes to one or many local inference boxes: DGX Spark / GB10, Ollama, vLLM or a LiteLLM gateway.

- Fleet registry (`hermes spark add / list / rm`), kinds ollama, vllm, litellm, openai-compatible
- Live health: up/down, latency, load from Ollama `/api/ps` or vLLM `/metrics`, free memory
- Freest-box routing with a no-flap margin, label preferences and pinning
- Modes: prefer-local, prefer-cloud, auto
- Failover to your cloud model when every box is down, **failback** when one recovers
- Works with core `fallback_providers` instead of replacing it; `restore` undoes everything
- CLI `hermes spark …`, slash `/spark`, Desktop status-bar chip + fleet panel, palette commands, opt-in DGX Spark theme
- Read-only agent tools plus an Ollama-only model pull; **no remote shell**

Point a node at LiteLLM to let LiteLLM balance, or let hermes-spark pick the freest box.

## PR description draft

Adds `plugin-catalog/hermes-spark.yaml`, a community plugin (repo: humedini/hermes-spark, MIT).

**What it does.** Registers a fleet of OpenAI-compatible inference boxes, probes their health and load, and makes the freest healthy one Hermes's primary model; fails over to the user's cloud model when every box is down and fails back when one recovers.

**Surfaces used.** `register_tool` (3, gated by `check_fn` on a non-empty fleet), `register_command` (`/spark`), `register_cli_command` (`hermes spark`), `register_hook` (`on_session_start`, background, bounded), `plugin_data_dir`, `ctx.set_config`, `hermes_cli.config.load_config` / `save_config` for the primary and `fallback_providers`, a unified Desktop half (`desktop/plugin.js`: statusbar chip, palette entries, a theme) and `dashboard/plugin_api.py` routes for it.

**Disclosures (rule 13).**
- Network: HTTP only to user-registered base URLs (`/models`, Ollama `/api/ps` and `/api/pull`, vLLM `/metrics`). No telemetry.
- Config writes: `model.provider`, `model.default`, `model.base_url`, `model.api_mode`, `model.key_env`, and one appended `fallback_providers` entry. The original primary is saved and `hermes spark restore` puts it back.
- Files: `fleet.json`, `state.json` in its plugin data dir.
- Background: a non-blocking probe on session start, at most once per `probe_interval_s`; `hermes spark watch` is foreground and user-started.
- Credentials: none stored; optional per-node keys by env var name via `agent.secret_scope.get_secret`.

**Checks.** `hermes plugins validate . --install-deps` passes; `hermes plugins doctor . --ci` passes; 48 unit tests.
