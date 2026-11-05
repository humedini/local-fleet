"""Probe -> decide -> apply, shared by the CLI, `/fleet`, the tools and the Desktop backend."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import aux, config_write, store, traffic
from .warm import warm
from .fleet import now_iso
from .bench import bench_node
from .health import probe_all
from .routing import decide, model_for, same_target

_lock = threading.Lock()  # one apply at a time within a process (watch + a slash command)
SERIES_LEN = 40   # probe points kept per node for the Desktop sparklines
HISTORY_LEN = 25  # routing changes kept for the Desktop timeline


def _age_s(iso: str | None) -> float:
    if not iso:
        return 1e12
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()


def run_bench(f, results: dict, settings: dict, nodes: list[dict], load: bool = False) -> dict:
    """Bench `nodes` in parallel (different machines) and record what came back."""
    want = settings.get("default_model") or ""
    if not nodes:
        return {}
    with ThreadPoolExecutor(max_workers=min(4, len(nodes))) as pool:
        futures = {n["id"]: pool.submit(bench_node, n, results.get(n["id"]), want, load) for n in nodes}
        out = {nid: fu.result() for nid, fu in futures.items()}
    f.record_perf(out)
    return out


def _due_for_bench(f, settings: dict) -> list[dict]:
    every = float(settings.get("bench_interval_s") or 0)
    if every <= 0:
        return []
    return [n for n in f.enabled()
            if min(_age_s((n.get("perf") or {}).get("at")), _age_s((n.get("perf_note") or {}).get("at"))) >= every]


def bench(refs: list[str] | None = None, load: bool = False) -> tuple[list[dict], dict]:
    """`hermes fleet bench`: probe, then bench the named nodes (all enabled ones by default)."""
    settings, f, results = probe()
    nodes = [f.get(r) for r in refs] if refs else f.enabled()
    return nodes, run_bench(f, results, settings, nodes, load)


def probe(settings: dict | None = None, auto_bench: bool = False):
    """Probe every enabled node and record the results. Returns (settings, fleet, results).
    With auto_bench, boxes whose speed is older than bench_interval_s are benched too."""
    settings = settings or store.read_settings()
    f = store.fleet()
    results = probe_all(f.enabled(), timeout=float(settings["probe_timeout_s"]),
                        want=settings.get("default_model") or "")
    f.record_health(results)
    if auto_bench:
        run_bench(f, results, settings, _due_for_bench(f, settings))
    stamp = now_iso()
    state = store.load_state()
    series = state.get("series") or {}
    for nid, snap in results.items():
        points = series.get(nid, [])[-(SERIES_LEN - 1):]
        points.append({"t": stamp, "lat": snap.get("latency_ms"), "load": snap.get("load_proxy"), "st": snap["status"]})
        series[nid] = points
    live = {n["id"] for n in f.nodes}
    state["series"] = {k: v for k, v in series.items() if k in live}
    state["last_probe_at"] = stamp
    store.save_state(state)
    return settings, f, results


def _cloud_ready(target: dict) -> bool:
    return bool(target.get("provider") and target.get("model"))


def apply_policy(dry_run: bool = False, pin: str | None = None, unpin: bool = False,
                 auto_bench: bool = False, aux_follow: bool = False) -> dict:
    """Probe, decide and, unless dry_run, write the primary when it changed.

    `pin` is a node id/name to use now and keep while it stays healthy (`hermes fleet use gx10`);
    `unpin` drops any pin first (`use --freest`, a mode change).
    """
    with _lock:
        settings, f, results = probe(auto_bench=auto_bench)
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
            decision["warning"] = f"{pin} is not available; picked a box automatically instead"
        if target["kind"] == "cloud" and not _cloud_ready(target):
            decision["applied"] = False
            decision["warning"] = ("no cloud target set (hermes fleet setup, or "
                                   "settings cloud_provider + cloud_model); primary left as is")
            store.update_state(last_decision=decision)
            return decision
        changed = decision["changed"] or (bool(pin) and not applied_now.get("pinned"))
        decision["applied"] = False
        if not dry_run and changed and target["kind"] == "local" and settings.get("warm_before_switch", True):
            snap = results.get(target["node_id"]) or {}
            decision["warm"] = warm(f.find(target["node_id"]), target.get("model", ""), snap.get("resident") or [],
                                    timeout=float(settings.get("warm_timeout_s") or 120))
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
        if not dry_run or aux_follow:  # side tasks are their own opt-in, independent of main routing
            decision["aux"] = _follow_aux(settings, f, results, decision, state)
        state["last_decision"] = decision
        if decision["applied"]:
            event = {"at": decision["at"], "reason": decision["reason"], "kind": target["kind"],
                     "node": target.get("node_name"), "model": target.get("model"), "via": target.get("via")}
            state["history"] = ((store.load_state().get("history") or []) + [event])[-HISTORY_LEN:]
        store.save_state({**store.load_state(), **state})
        return decision


def _follow_aux(settings, f, results, decision, state) -> str | None:
    """Keep the auxiliary tasks on the freest healthy box (whatever the mode), or put the user's own
    blocks back when no box is healthy. Writes only when the target changes. Updates `state`."""
    tasks = list(settings.get("aux_tasks") or [])
    current = state.get("aux_applied")
    if not tasks:
        return None
    node = f.find(decision.get("freest_node_id") or "")
    if node is None:
        if current:
            aux.apply(current["tasks"], None, state.get("aux_original") or {})
            state["aux_applied"] = None
            return "no healthy box: side tasks back on their own settings"
        return None
    model = model_for(node, results.get(node["id"]) or {}, settings.get("default_model") or "")
    want = {"tasks": tasks, "node_id": node["id"], "node_name": node["name"], "model": model}
    if current == want:
        return None
    before = aux.apply(tasks, aux.block(node, model, settings.get("cloud_provider"), settings.get("cloud_model")), None)
    original = state.get("aux_original") or {}
    for t in tasks:
        original.setdefault(t, before.get(t, {}))
    state["aux_original"] = original
    state["aux_applied"] = want
    return f"side tasks → {node['name']} · {model}"


def aux_off() -> list[str]:
    with _lock:
        state = store.load_state()
        current = state.get("aux_applied")
        store.write_setting("aux_tasks", [])
        if not current:
            return []
        aux.apply(current["tasks"], None, state.get("aux_original") or {})
        state["aux_applied"] = None
        state.pop("aux_original", None)
        store.save_state(state)
        return current["tasks"]


def restore() -> dict | None:
    """Put back the primary the user had before local-fleet first changed it."""
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
    """Everything the chip, `/fleet` and `fleet_status` show, from stored state (no probing)."""
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
    primary = {k: v for k, v in config_write.current_primary().items() if k != "key_env"}
    stats = traffic.summarize(traffic.load(), (float(settings.get("price_in_per_m") or 0),
                                               float(settings.get("price_out_per_m") or 0)))
    return {
        "mode": settings["mode"],
        "label": label,
        "primary": primary,
        "local_model": settings.get("default_model") or "",
        "applied": applied,
        "down": bool(f.enabled()) and not healthy and applied.get("kind") != "cloud",
        "nodes": len(f.nodes),
        "healthy": len(healthy),
        "last_decision": state.get("last_decision"),
        "last_probe_at": state.get("last_probe_at"),
        "series": state.get("series") or {},
        "traffic": stats,
        "currency": settings.get("currency") or "USD",
        "aux": state.get("aux_applied"),
        "delegation_backend": store.delegation_backend(),
        "delegations": (state.get("delegations") or [])[-10:],
        "history": state.get("history") or [],
        "fallback_chain": [{k: e.get(k) for k in ("provider", "model")} for e in config_write.fallback_chain()
                           if isinstance(e, dict)],
    }
