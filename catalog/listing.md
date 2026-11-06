# Catalog listing copy

## Short (≤200 chars)

Your local inference fleet, operated from Hermes Desktop: Hermes runs on the least busy box, shows why, falls back to cloud when boxes are down and comes back when they recover.

## Long

**local-fleet** connects Hermes to one or many local inference boxes: DGX Spark / GB10, Ollama, vLLM or a LiteLLM gateway.

- Fleet registry (`hermes fleet add / list / rm`), kinds ollama, vllm, litellm, openai-compatible
- Live health: up/down, latency, load from Ollama `/api/ps` or vLLM `/metrics`, free memory
- Least-busy-box routing that does not flip-flop, with label preferences and pinning
- A guided demo, rehearsal packs, and scrubbed incident cards and savings receipts to paste anywhere
- Operations: why-this-box inspector, flight recorder (configured vs served), outage rehearsal, maintenance, drift detection that never fights other plugins, readiness evidence per box and model, an auditable savings breakdown, doctor with one-click fixes
- Private inference: primary, fallback_providers, side tasks and subagents held to your boxes, failing rather than using cloud, with a status that says when something outside Local Fleet breaks it (not air-gapping)
- Modes: prefer-local, prefer-cloud, auto
- Failover to your cloud model when every box is down, **failback** when one recovers
- Works with core `fallback_providers` instead of replacing it; `restore` puts your original primary model back (`aux off`, `delegate off` and `keep off` undo the optional features)
- CLI `hermes fleet …`, slash `/fleet`, Desktop status-bar chip + fleet panel, palette commands, opt-in DGX Spark theme
- Read-only agent tools plus an Ollama-only model pull; **no remote shell**

Point a node at LiteLLM to let LiteLLM balance, or let Local Fleet pick the least busy box.

## PR description draft

Adds `plugin-catalog/local-fleet.yaml`, a community plugin (repo: humedini/local-fleet, MIT).

**What it does.** Registers a fleet of OpenAI-compatible inference boxes, probes their health and load, and makes the least busy one Hermes's primary model; fails over to the user's cloud model when every box is down and fails back when one recovers.

**Surfaces used.** `register_tool` (3, gated by `check_fn` on a non-empty fleet), `register_command` (`/fleet`), `register_cli_command` (`hermes fleet`), `register_hook` (`on_session_start`, background, bounded; observer hooks `post_api_request`, `api_request_error`, `post_auxiliary_call`, one small append per call), `register_skill`, `register_delegation_provider` (backend `fleet`), `plugin_data_dir`, `ctx.set_config`, `hermes_cli.config.load_config` / `save_config` for the primary and `fallback_providers`, a unified Desktop half (`desktop/plugin.js`: statusbar chip, palette entries, a theme) and `dashboard/plugin_api.py` routes for it.

**Disclosures (rule 13).**
- Network: the cloud price via Hermes's own rate card (`agent.usage_pricing`, at most daily, only when no price is set); otherwise HTTP only to user-registered base URLs (`/models`; Ollama `/api/ps`, `/api/show`, `/api/version`, `/api/generate` for benches, warm-up and keep-loaded, `/api/pull` on request; vLLM `/metrics`). No telemetry.
- Config writes: `model.provider`, `model.default`, `model.base_url`, `model.api_mode`, `model.key_env`, and one appended `fallback_providers` entry. The original primary is saved and `hermes fleet restore` puts it back. On request: `delegation.backend` (`delegate on/off`) and `auxiliary.<task>` `provider`/`model`/`base_url`/`fallback_chain` (`aux on/off`, previous blocks restored; a task with its own `api_key` is never taken over). With `private on`: non-local `fallback_providers` entries removed and put back on `off`, `delegation.backend: fleet` with the previous backend put back on `off`, managed side tasks without a cloud `fallback_chain`. Changes made by others are reported as drift, never overwritten silently.
- Files: `fleet.json`, `state.json`, `events.jsonl` (addresses masked before storing), `traffic.jsonl` (per call: endpoint, model, tokens, duration; no content) in its plugin data dir.
- Background: a non-blocking probe on session start, at most once per `probe_interval_s`; observer hooks append one line per model call; `hermes fleet watch` is foreground and user-started.
- Private inference scope: Hermes's model routing only (primary, fallback chain, side tasks, subagents on the `fleet` backend); reported as not in force when anything it does not own points at cloud. Not air-gapping: tools still use the internet.
- Credentials: none stored; optional per-node keys by env var name via `agent.secret_scope.get_secret`.

**Checks.** CI runs the unit tests on Python 3.11-3.14 and `hermes plugins validate` + `hermes plugins doctor --ci` against a pinned Hermes.
