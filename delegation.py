"""`delegation.backend: fleet`: run subagents on the fleet, spread across boxes.

Each `delegate_task` task gets the freest healthy box; tasks routed close together (one fan-out)
take turns down the freest-first list, so four subagents land on four boxes rather than one. A
task may ask for `where: cloud` (a frontier model) or `local`; `any` (the default) means local
when a box is healthy, else cloud. Every local route carries the cloud model as its fallback.

Routing reads the box health the plugin already recorded (no probing on the delegation path),
so it is instant; `task_parameters` and `description` are fixed text, so the delegate_task
schema never changes under a running session (prompt cache).
"""
from __future__ import annotations

import threading
import time

from . import store
from .fleet import now_iso
from .health import routable, score
from .routing import choose_tier, model_for

NAME = "fleet"
WHERE = ("any", "local", "cloud")
FANOUT_WINDOW_S = 20.0

_lock = threading.Lock()
_turn = {"at": 0.0, "i": 0}


def _cloud(settings: dict, label: str = "cloud") -> dict:
    return {"provider": settings.get("cloud_provider") or "", "model": settings.get("cloud_model") or "", "label": label}


def _next_index() -> int:
    """Position in the freest-first list: advances within one fan-out, restarts after a pause."""
    with _lock:
        now = time.monotonic()
        _turn["i"] = _turn["i"] + 1 if now - _turn["at"] < FANOUT_WINDOW_S else 0
        _turn["at"] = now
        return _turn["i"]


def route(task: dict, settings: dict, nodes: list[dict], secret=None) -> dict:
    """The route for one task (pure apart from the fan-out counter)."""
    where = task.get("where") or "any"
    if where == "cloud":
        return _cloud(settings)
    labels = settings.get("prefer_labels") or ()
    want, _tier = choose_tier(nodes, {n["id"]: n.get("last_health") for n in nodes}, settings)
    healthy = [n for n in nodes if n.get("enabled", True) and routable(n, n.get("last_health"), want)]
    if not healthy:
        if where == "local":
            raise LookupError("no healthy local box for a where=local task")
        return _cloud(settings, "cloud (no healthy box)")
    ranked = sorted(healthy, key=lambda n: score(n, n["last_health"], labels, want))
    node = ranked[_next_index() % len(ranked)]
    r = {"provider": "custom", "base_url": node["base_url"], "api_mode": "chat_completions",
         "model": model_for(node, node["last_health"], want), "label": node["name"]}
    if node.get("api_key_env") and secret:
        r["api_key"] = secret(node["api_key_env"]) or ""
    if settings.get("cloud_provider") and settings.get("cloud_model"):
        r["fallback_providers"] = [{"provider": settings["cloud_provider"], "model": settings["cloud_model"]}]
    return r


def note(r: dict) -> None:
    """Remember the last routes for the Desktop map (box name and time only, never the task)."""
    try:
        state = store.load_state()
        state["delegations"] = ((state.get("delegations") or []) + [{"at": now_iso(), "label": r.get("label")}])[-30:]
        store.save_state(state)
    except Exception:
        pass


def make_provider():
    """The provider object, or None outside Hermes (unit tests import this module without it)."""
    try:
        from agent.delegation_provider import DelegationProvider, DelegationRouteError
    except ImportError:
        return None

    class FleetDelegation(DelegationProvider):
        @property
        def name(self) -> str:
            return NAME

        @property
        def display_name(self) -> str:
            return "Local Fleet"

        @property
        def summary(self) -> str:
            return "Subagents run on your local boxes, freest first and spread across them; cloud when none is up."

        def task_parameters(self, config):
            return {"where": {
                "type": "string", "enum": list(WHERE),
                "description": ("Where this subagent runs. any (default): a local inference box when one is "
                                "healthy, else cloud. local: only a local box. cloud: the user's cloud model, "
                                "for tasks that need a frontier model."),
            }}

        def description(self, config):
            return ("Subagents run on the user's own inference boxes (Local Fleet); several subagents in one "
                    "call are spread across boxes and run in parallel. Use where=cloud only when a task "
                    "needs a stronger model than the local one.")

        def route_task(self, task, config):
            from agent.secret_scope import get_secret
            try:
                r = route(dict(task), store.read_settings(), store.fleet().nodes, get_secret)
            except LookupError as e:
                raise DelegationRouteError(str(e))
            if not r.get("model"):
                raise DelegationRouteError("Local Fleet has no cloud model set (hermes fleet cloud <provider> <model>).")
            note(r)
            return r

    return FleetDelegation()
