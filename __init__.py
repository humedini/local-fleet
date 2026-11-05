"""hermes-spark: health-aware routing across a fleet of Spark / Ollama-compatible boxes.

register() only wires things up: no network, no config reads (doctor blocks sockets while it
runs, and settings are read when a command or tool actually runs).
"""
from __future__ import annotations

import threading

from . import cli, schemas, slash, store, tools
from .constants import TOOLSET

_bg = threading.Lock()


def _refresh_on_session_start(**kwargs) -> None:
    """New session: re-route in the background if the watch loop has not probed recently, so
    the next message goes to a live box. Never blocks the session."""
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
                engine.apply_policy()
        except Exception:
            pass  # a failed background probe must never surface in someone's session
        finally:
            _bg.release()

    threading.Thread(target=run, name="hermes-spark-refresh", daemon=True).start()


def register(ctx):
    store.bind(ctx)
    for schema, handler in ((schemas.SPARK_STATUS, tools.spark_status),
                            (schemas.SPARK_LIST_NODES, tools.spark_list_nodes),
                            (schemas.SPARK_PULL_MODEL, tools.spark_pull_model)):
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler,
                          check_fn=tools.fleet_ready, emoji="💚")
    ctx.register_command("spark", handler=slash.handle,
                         description="Spark fleet: status, list, mode, use, doctor",
                         args_hint="[status|list|mode|use|doctor]")
    ctx.register_cli_command(name="spark", help="Route Hermes across Spark / Ollama-compatible boxes",
                             setup_fn=cli.setup_argparse, handler_fn=cli.main,
                             description="Fleet registry, health probes, freest-box routing, "
                                         "cloud failover and failback.")
    ctx.register_hook("on_session_start", _refresh_on_session_start)
