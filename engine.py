"""Probe -> decide -> apply, shared by the CLI, `/spark`, the tools and the Desktop backend."""
from __future__ import annotations

import threading

from . import config_write, store
from .fleet import now_iso
from .health import probe_all
from .routing import decide, same_target

_lock = threading.Lock()  # one apply at a time within a process (watch + a slash command)


def probe(settings: dict | None = None):
    """Probe every enabled node and record the results. Returns (settings, fleet, results)."""
    settings = settings or store.read_settings()
    f = store.fleet()
    results = probe_all(f.enabled(), timeout=float(settings["probe_timeout_s"]),
                        want=settings.get("default_model") or "")
    f.record_health(results)
    store.update_state(last_probe_at=now_iso())
    return settings, f, results


def _cloud_ready(target: dict) -> bool:
    return bool(target.get("provider") and target.get("model"))


def apply_policy(dry_run: bool = False, pin: str | None = None, unpin: bool = False) -> dict:
    """Probe, decide and, unless dry_run, write the primary when it changed.

    `pin` is a node id/name to use now and keep while it stays healthy (`hermes spark use gx10`);
    `unpin` drops any pin first (`use --freest`, a mode change).
    """
    with _lock:
        settings, f, results = probe()
        state = store.load_state()
        applied_now = dict(state.get("applied") or {})
        current = dict(applied_now)
        if unpin:  # an explicit "go freest": no pin, and no stickiness to the active node
            current = {k: v for k, v in current.items() if k not in ("pinned", "node_id")}
        if pin:
            node = f.get(pin)
            current = {"kind": "local", "node_id": node["id"], "model": current.get("model", ""),
                       "pinned": True}
        decision = decide(settings, f.nodes, results, current)
        decision["changed"] = not same_target(decision["target"], applied_now)
        target = decision["target"]
        if pin and target.get("node_id") != current["node_id"]:
            decision["warning"] = f"{pin} is not healthy; routed by policy instead"
        if target["kind"] == "cloud" and not _cloud_ready(target):
            decision["applied"] = False
            decision["warning"] = ("no cloud target set (hermes spark setup, or "
                                   "settings cloud_provider + cloud_model); primary left as is")
            store.update_state(last_decision=decision)
            return decision
        changed = decision["changed"] or (bool(pin) and not applied_now.get("pinned"))
        decision["applied"] = False
        if not dry_run and changed:
            node = f.find(target.get("node_id") or "")
            before = config_write.set_primary(config_write.model_block(target, node))
            if "original_model" not in state:
                state["original_model"] = before
            applied = {k: target.get(k) for k in ("kind", "node_id", "node_name", "base_url", "provider", "model", "via")}
            if pin and target.get("node_id") == current["node_id"]:
                applied["pinned"] = True
            state["applied"] = {k: v for k, v in applied.items() if v is not None}
            decision["applied"] = True
        if not dry_run and _cloud_ready({"provider": settings.get("cloud_provider"),
                                         "model": settings.get("cloud_model")}):
            decision["fallback_added"] = config_write.ensure_fallback(settings["cloud_provider"], settings["cloud_model"])
        state["last_decision"] = decision
        store.save_state({**store.load_state(), **state})
        return decision


def restore() -> dict | None:
    """Put back the primary the user had before hermes-spark first changed it."""
    with _lock:
        state = store.load_state()
        original = state.get("original_model")
        if original is None:
            return None
        config_write.set_primary(original)
        state.pop("applied", None)
        state.pop("original_model", None)
        state["last_decision"] = {"at": now_iso(), "reason": "restored the original primary"}
        store.save_state(state)
        return original


def snapshot() -> dict:
    """Everything the chip, `/spark` and `spark_status` show, from stored state (no probing)."""
    settings = store.read_settings()
    f = store.fleet()
    state = store.load_state()
    applied = state.get("applied") or {}
    if applied.get("kind") == "local":
        label = applied.get("node_name") or "local"
    elif applied.get("kind") == "cloud":
        label = "cloud"
    else:
        label = "off"
    healthy = [n for n in f.enabled() if (n.get("last_health") or {}).get("status") in ("ok", "degraded")]
    return {
        "mode": settings["mode"],
        "label": label,
        "applied": applied,
        "down": bool(f.enabled()) and not healthy and applied.get("kind") != "cloud",
        "nodes": len(f.nodes),
        "healthy": len(healthy),
        "last_decision": state.get("last_decision"),
        "last_probe_at": state.get("last_probe_at"),
    }
