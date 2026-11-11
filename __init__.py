"""local-fleet: health-aware routing across your own inference boxes (DGX Spark, Ollama, vLLM, LiteLLM).

register() only wires things up: no network, no config reads (doctor blocks sockets while it
runs, and settings are read when a command or tool actually runs).
"""
from __future__ import annotations

import contextvars
import threading
from pathlib import Path

from . import cli, delegation, schemas, slash, store, tools, traffic
from .constants import TOOLSET

_bg = threading.Lock()


def _refresh_on_session_start(**kwargs) -> None:
    """New session: refresh health (and speed, when due) in the background if nothing probed
    recently; once the user has routed with `use` / `mode` / `watch`, also keep that routing
    current (failover, failback). Before that it never changes the primary. Never blocks."""
    if not tools.fleet_ready() or not _bg.acquire(blocking=False):
        return

    def run():
        try:
            from datetime import datetime, timezone
            from . import engine
            settings, state = store.read_settings(), store.load_state()
            last = state.get("last_probe_at")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() if last else 1e9
            if age >= float(settings["probe_interval_s"]):
                # Routing is opt-in: only an explicit use/mode/watch sets "applied".
                engine.apply_policy(dry_run=not state.get("applied"), auto_bench=True, aux_follow=True)
        except Exception:
            pass  # a failed background probe must never surface in someone's session
        finally:
            _bg.release()

    # Hermes keeps the active profile in a context variable: carry it into the thread, so a gateway
    # serving several profiles refreshes (and writes) the session's profile, not the launch one.
    threading.Thread(target=contextvars.copy_context().run, args=(run,), name="local-fleet-refresh",
                     daemon=True).start()


def register(ctx):
    store.bind(ctx)
    for schema, handler in ((schemas.FLEET_STATUS, tools.fleet_status),
                            (schemas.FLEET_LIST_NODES, tools.fleet_list_nodes),
                            (schemas.FLEET_PULL_MODEL, tools.fleet_pull_model)):
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler,
                          check_fn=tools.fleet_ready, emoji="💚")
    ctx.register_command("fleet", handler=slash.handle,
                         description="Local inference fleet: status, list, mode, use, doctor",
                         args_hint="[status|list|mode|use|doctor]")
    ctx.register_cli_command(name="fleet", help="Route Hermes across your local inference boxes (DGX Spark, Ollama, vLLM)",
                             setup_fn=cli.setup_argparse, handler_fn=cli.main,
                             description="Fleet registry, health probes, freest-box routing, "
                                         "cloud failover and failback.")
    ctx.register_hook("on_session_start", _refresh_on_session_start)
    ctx.register_hook("pre_tool_call", tools.pull_approval)  # pulls need a human's yes
    # Real-traffic stats: endpoint, tokens and duration of each call (never its content).
    ctx.register_hook("post_api_request", traffic.on_post_api_request)
    ctx.register_hook("api_request_error", traffic.on_api_request_error)
    ctx.register_hook("post_auxiliary_call", traffic.on_post_auxiliary_call)
    provider = delegation.make_provider()
    if provider is not None:
        ctx.register_delegation_provider(provider)
    ctx.register_skill("local-fleet", Path(__file__).parent / "skills" / "local-fleet" / "SKILL.md")
