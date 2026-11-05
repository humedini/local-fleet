# hermes-spark

**Route Hermes across a fleet of local inference boxes, and fall back to cloud only when you have to.**

Register your DGX Spark / GB10 boxes, Ollama hosts, vLLM servers or a LiteLLM gateway. hermes-spark probes them, picks the freest healthy one, makes it Hermes's primary model, and moves you to cloud when every box is down. When a box comes back it fails back to local. A Desktop status-bar chip shows where you are routed; `/spark` and `hermes spark` do the same from chat and the terminal.

```
$ hermes spark status
  name         status    health                 kind              url
  gx10         ok        5ms load=0.207 free=95GB ollama            http://192.168.1.50:11434/v1  ← active
  spark2       ok        3ms load=0             ollama            http://192.168.1.51:11434/v1  (freest)
  mini         ok        21ms load=0.25         ollama            http://192.168.1.52:11434/v1  ok, but no qwen3.6:35b-a3b

mode: auto
route: gx10 · qwen3.6:35b-a3b · http://192.168.1.50:11434/v1
why: staying on gx10
```

It is a standalone plugin, not a core change: it writes the same config keys you would set by hand, and leaves turn-level failover to Hermes's own `fallback_providers`.

## Install

```bash
hermes plugins install humedini/hermes-spark
hermes plugins enable hermes-spark
hermes spark setup          # or the three commands below
```

Requires Hermes 0.22 or newer. One dependency: `httpx`.

```bash
hermes spark add --name gx10 --url http://192.168.1.50:11434/v1 --kind ollama --label lan --capacity-gb 120
hermes spark add --name spark2 --url http://192.168.1.51:11434/v1 --kind ollama
hermes spark cloud openrouter anthropic/claude-sonnet-4     # the backup when every box is down
hermes spark model qwen3.6:35b-a3b                          # optional: the model to run locally
hermes spark use --freest
```

## Modes

| Mode | Primary | When every local box is down | When a box recovers |
|---|---|---|---|
| `prefer-local` | freest healthy local box | cloud becomes primary | back to the freest local box |
| `auto` (default) | same as prefer-local | same | same |
| `prefer-cloud` | your cloud target | stays cloud | stays cloud; `hermes spark use <box>` routes locally on demand |

`auto` and `prefer-local` behave the same today; `auto` is the name to use if you want future policy refinements (time of day, cost) to apply. Turn failback off with the `failback_enabled` setting to stay on cloud after a failover until you choose.

## How it picks a box

Every kind answers `GET {base}/models`, which decides up or down and gives latency. On top of that:

- **ollama**: `GET /api/ps`. Other models resident in memory count as load (0.25 each, or memory used divided by `--capacity-gb` when you give it), so a box that already holds the model you want looks freer and you skip a cold load.
- **vllm**: `GET /metrics`, using `vllm:gpu_cache_usage_perc` (or running requests).
- **litellm, openai-compatible**: latency only.

Lowest load wins, then preferred labels (`prefer_labels`), then most free memory, then latency, then name. If you set a local model (`hermes spark model`), boxes that do not serve it are skipped. A box whose models answer but whose load endpoint fails is *degraded* and still routable.

It does not flap. A healthy active box is kept unless another is more than `switch_margin` (default 0.25) freer. `hermes spark use gx10` pins a box while it stays healthy; `use --freest` or a mode change drops the pin.

## What it changes in your Hermes config

Only these keys, through Hermes's own config writer (comments and formatting are kept):

- `model.provider`, `model.default`, `model.base_url`, `model.api_mode`, `model.key_env` — the primary. Local box: `provider: custom` with the box's base URL. Cloud: your `cloud_provider` and `cloud_model`. Other `model:` keys such as `context_length` are left alone.
- `fallback_providers` — your cloud target is appended once if it is not already there.

The first time it changes the primary it saves what you had. `hermes spark restore` puts it back.

### Coordinating with `fallback_providers`

hermes-spark chooses the **primary**. Hermes core owns the **per-turn** fallback chain: if the primary errors mid-turn, core moves to the next entry for that turn and returns to the primary on the next. hermes-spark never runs a second chain; it only makes sure your cloud entry is on core's. The two together give you a fast, health-aware choice of box between turns and core's safety net within a turn.

### When a change takes effect

The gateway and Desktop rebuild the agent when the primary changes, so a new route applies from the **next message**. A classic CLI session that is already open keeps its model until the next session. This is deliberate: Hermes keeps a conversation on one model so its prompt cache stays valid.

## Keeping it current

Routing is re-evaluated when you run a command, when a new session starts (in the background, at most once per `probe_interval_s`), and continuously with:

```bash
hermes spark watch --interval 20      # foreground; Ctrl-C to stop
hermes spark watch --once             # one tick, for cron or a systemd timer
```

## LiteLLM

Two supported setups:

1. **hermes-spark picks the box** (the default story): register each box; the plugin chooses.
2. **LiteLLM balances**: register your LiteLLM proxy as one node with `--kind litellm`. hermes-spark health-checks that gateway and fails over to cloud if it dies; balancing across boxes is LiteLLM's job.

hermes-spark does not replace LiteLLM; it gives you health-aware routing without running one.

## Commands

| | |
|---|---|
| `hermes spark setup` | guided first run |
| `hermes spark add --name --url [--kind] [--label] [--api-key-env] [--capacity-gb]` | register a box |
| `hermes spark rm / enable / disable <box>` | manage boxes |
| `hermes spark list [--json]` | boxes and their last health |
| `hermes spark status [--json]` | probe and show where it would route (changes nothing) |
| `hermes spark use <box> \| --freest` | route now |
| `hermes spark mode [prefer-local\|prefer-cloud\|auto]` | show or set the mode |
| `hermes spark cloud [<provider> <model>]` | show or set the cloud target |
| `hermes spark model [<id>]` | show or set the local model |
| `hermes spark watch [--interval s] [--once]` | keep routing current |
| `hermes spark endpoint` | the primary Hermes is using |
| `hermes spark doctor` | readiness check |
| `hermes spark restore` | put back your original primary |

In chat: `/spark`, `/spark list`, `/spark mode auto`, `/spark use freest`, `/spark use gx10`, `/spark doctor`.

## Agent tools

- `spark_status` — probe the fleet and report health, load, models and the route. Read-only.
- `spark_list_nodes` — the registry with last health, no probing. Read-only.
- `spark_pull_model` — pull a model onto one **Ollama** box through Ollama's pull API. The tool description asks the agent to confirm first.

The tools are hidden until at least one box is registered. There is no tool that runs commands on a box, and there never will be.

## Desktop

The Desktop half adds a status-bar chip (`spark · gx10 · auto`, a green dot when routed locally, `down` when nothing is healthy). Click it for the fleet panel: each box with a health dot and load bar, the mode switch, **Use freest**, **Probe now**, and **Spark look**, which switches to the bundled black-and-green *DGX Spark* theme (listed under themes, never selected for you). The command palette gets *Spark: route to the freest box*, *Spark: probe the fleet* and one entry per mode.

The Desktop half needs the plugin enabled for the agent and a gateway restart, so its backend routes (`/api/plugins/hermes-spark/*`) are mounted.

## Keys

Boxes on your LAN or tailnet usually need none. For one that does, store the key as a Hermes secret and give its **name**:

```bash
hermes spark add --name lab --url https://vllm.lab.example/v1 --kind vllm --api-key-env LAB_VLLM_KEY
```

The key is read with Hermes's secret resolver when that box is probed or used and sent to that box only. `fleet.json` holds the variable name, never the value, and the agent tools and Desktop never see either.

## Disclosures

- **Network**: HTTP requests go only to the base URLs you register (`/models`, plus `/api/ps` for Ollama or `/metrics` for vLLM), and to Ollama's `/api/pull` when the agent uses `spark_pull_model`. Nothing else, no telemetry.
- **Files**: reads and writes `fleet.json` and `state.json` in its own plugin data directory; writes the config keys listed above.
- **Background work**: a short background probe when a session starts (at most once per `probe_interval_s`). `hermes spark watch` runs only when you start it.
- **Credentials**: none stored. Optional per-box keys are read by env var name through Hermes's secret resolver.
- **Plain HTTP**: Ollama and vLLM usually serve plain HTTP. `doctor` warns if a box's URL is plain HTTP to a public address; keep boxes on your LAN, a tailnet or behind TLS.

## Not in scope

Starting or stopping inference servers, multi-box model sync, NVIDIA NIM management, mixture-of-agents. hermes-spark routes between servers you already run.

## Develop

```bash
python -m venv .venv && .venv/bin/pip install httpx pyyaml pytest respx fastapi
.venv/bin/python -m pytest tests -q
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

Try it without touching your real Hermes home:

```bash
export HERMES_HOME=$(mktemp -d)
mkdir -p $HERMES_HOME/plugins && ln -s "$PWD" $HERMES_HOME/plugins/hermes-spark
hermes plugins enable hermes-spark && hermes spark setup
```

Tested with Hermes 0.22.7 on Linux against a GB10 box (ASUS Ascent GX10), an AMD Strix Halo laptop and an Apple silicon Mac, all running Ollama.

## Licence

MIT
