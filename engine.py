"""Probe -> decide -> apply, shared by the CLI, `/fleet`, the tools and the Desktop backend."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import aux, config_write, events, readiness, store, traffic
from .warm import warm
from .fleet import now_iso
from .bench import bench_node
from .health import probe_all, routable, score
from .routing import check, decide, model_for, model_tiers, same_target

SERIES_LEN = 40   # probe points kept per node for the Desktop sparklines
HISTORY_LEN = 25  # routing changes kept for the Desktop timeline


def _couple_clusters(f, results: dict) -> None:
    """A cluster's members carry its load: while the big model is busy, the boxes it spans are not
    free for single-box work (their own endpoints cannot see memory the cluster uses)."""
    for c in f.nodes:
        snap = results.get(c["id"])
        if not c.get("members") or not snap or snap.get("status") not in ("ok", "degraded"):
            continue
        for mid in c["members"]:
            m = results.get(mid)
            if not m:
                continue
            m["in_cluster"] = c["name"]
            if snap.get("load_proxy") is not None:
                m["load_proxy"] = round(max(m.get("load_proxy") or 0.0, snap["load_proxy"]), 3)


def _age_s(iso: str | None) -> float:
    if not iso:
        return 1e12
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()


def run_bench(f, results: dict, settings: dict, nodes: list[dict], load: bool = False) -> dict:
    """Bench `nodes` in parallel (different machines) and record what came back."""
    want = [m for m in model_tiers(settings) if m]
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
                        want=[m for m in model_tiers(settings) if m])
    _couple_clusters(f, results)
    before = {n["id"]: (n.get("last_health") or {}).get("status") for n in f.nodes}
    f.record_health(results)
    for n in f.nodes:
        was, now = before.get(n["id"]), (results.get(n["id"]) or {}).get("status")
        if now and was and (was in ("ok", "degraded")) != (now in ("ok", "degraded")):
            detail = "" if now in ("ok", "degraded") else f": {(results[n['id']] or {}).get('detail', '')}"
            events.record("health", f"{n.get('title') or n['name']} {'is back' if now in ('ok', 'degraded') else 'went down'}{detail}",
                          box=n["name"], status=now)
    try:
        caps = readiness.refresh(f.enabled(), results, [m for m in model_tiers(settings) if m])
        if caps:
            f.record_caps(caps)
    except Exception:
        pass  # readiness is evidence for display and routing; a failed check leaves it unknown
    if auto_bench:
        run_bench(f, results, settings, _due_for_bench(f, settings))
    stamp = now_iso()
    with store.transaction():
        state = store.load_state()
        series = state.get("series") or {}
        for nid, snap in results.items():
            points = series.get(nid, [])[-(SERIES_LEN - 1):]
            points.append({"t": stamp, "lat": snap.get("latency_ms"), "load": snap.get("load_proxy"), "st": snap["status"]})
            series[nid] = points
        live = {n["id"] for n in store.fleet().nodes}
        state["series"] = {k: v for k, v in series.items() if k in live}
        state["last_probe_at"] = stamp
        store.save_state(state)
    return settings, f, results


def _aux_drift(applied: dict) -> list[str]:
    """Side tasks whose block no longer points where Local Fleet put them."""
    node = store.fleet().find(applied.get("node_id") or "")
    aux_cfg = config_write._load().get("auxiliary") or {}
    out = []
    for t in applied.get("tasks") or []:
        b = aux_cfg.get(t) or {}
        if node is None or b.get("base_url") != node["base_url"] or b.get("model") != applied.get("model"):
            out.append(t)
    return out


def drift(state: dict | None = None) -> list[dict]:
    """What Local Fleet wrote that is no longer in Hermes's config: [{"what", "detail"}]."""
    state = state if state is not None else store.load_state()
    out = []
    if state.get("paused"):
        out.append({"what": "primary", "detail": "the primary model was changed outside Local Fleet; routing is paused"})
    entry = state.get("fallback_ensured")
    if entry and not config_write.has_fallback(config_write.fallback_chain(), entry.get("provider"), entry.get("model")):
        out.append({"what": "fallback", "detail": f"your cloud entry {entry['provider']}/{entry['model']} was removed from fallback_providers"})
    if state.get("aux_applied"):
        changed = _aux_drift(state["aux_applied"])
        if changed or state.get("aux_paused"):
            out.append({"what": "side tasks", "detail": f"{', '.join(changed) or 'side tasks'} changed outside Local Fleet"})
    return out


def reapply() -> dict:
    """Take routing back after drift: primary (auto-pick), cloud entry, side tasks."""
    with store.transaction():
        state = store.load_state()
        for k in ("paused", "aux_paused", "fallback_ensured"):
            state.pop(k, None)
        if state.get("aux_applied"):
            state["aux_applied"] = None  # re-applied fresh below
        store.save_state(state)
    events.record("drift", "reapplied Local Fleet's routing")
    return apply_policy(unpin=True)


def relinquish() -> str:
    """Stop managing Hermes's routing, leaving the config exactly as it is now."""
    with store.transaction():
        state = store.load_state()
        state.update({"applied": None, "paused": True, "aux_applied": None, "fallback_ensured": None})
        state.pop("aux_paused", None)
        state.pop("original_model", None)
        store.save_state(state)
    store.write_setting("aux_tasks", [])
    events.record("drift", "relinquished: Local Fleet stopped managing routing; config left as it is")
    return "Local Fleet no longer manages routing; Hermes's config is untouched. Auto-pick box takes it back."


def active_exclusions(state: dict) -> dict:
    """Boxes left out of selection: maintenance (until turned off) and rehearsals (until they
    expire; an expired one is dropped from `state` and recorded)."""
    out, now = {}, datetime.now(timezone.utc)
    for nid, ex in list((state.get("exclusions") or {}).items()):
        until = ex.get("until")
        if until and datetime.fromisoformat(until) <= now:
            state["exclusions"].pop(nid, None)
            events.record("rehearsal", f"rehearsal ended: {ex.get('label') or nid} is back in selection", box=ex.get("label"))
            continue
        out[nid] = ex
    return out


def _changed_outside(state: dict) -> bool:
    """True when the plugin routed Hermes but the primary in config is no longer what it wrote."""
    applied = state.get("applied") or {}
    if not applied.get("kind"):
        return False
    want = config_write.model_block(applied, None)
    have = config_write.current_primary()
    return any(have.get(k) != want.get(k) for k in ("provider", "default", "base_url"))


def _cloud_ready(target: dict) -> bool:
    return bool(target.get("provider") and target.get("model"))


def apply_policy(dry_run: bool = False, pin: str | None = None, unpin: bool = False,
                 auto_bench: bool = False, aux_follow: bool = False) -> dict:
    """Probe, decide and, unless dry_run, write the primary when it changed.

    `pin` is a node id/name to use now and keep while it stays healthy (`hermes fleet use gx10`);
    `unpin` drops any pin first (`use --freest`, a mode change).
    """
    with store.transaction():
        settings, f, results = probe(auto_bench=auto_bench)
        state = store.load_state()
        manual = _changed_outside(state)
        if manual and not (pin or unpin):
            # The user changed the primary themselves: respect it. Routing stays paused until they
            # choose a box or Auto-pick again (pin / unpin); the saved original is stale now.
            state.pop("applied", None)
            state.pop("original_model", None)
            state["paused"] = True
            store.save_state({**store.load_state(), "applied": None, "original_model": None, "paused": True})
        if pin or unpin:
            state.pop("paused", None)
        elif state.get("paused"):
            dry_run = True
        applied_now = dict(state.get("applied") or {})
        current = dict(applied_now)
        if unpin:  # an explicit "go freest": no pin, and no stickiness to the active node
            current = {k: v for k, v in current.items() if k not in ("pinned", "node_id")}
        if pin:
            node = f.get(pin)
            current = {"kind": "local", "node_id": node["id"], "model": current.get("model", ""),
                       "pinned": True}
        excluded = active_exclusions(state)
        decision = decide(settings, f.nodes, results, current, excluded)
        decision["changed"] = not same_target(decision["target"], applied_now)
        target = decision["target"]
        if pin and target.get("node_id") != current["node_id"]:
            decision["warning"] = f"{pin} is not available; picked a box automatically instead"
        if target["kind"] == "refused":
            decision["applied"] = False
            decision["warning"] = target["reason"]
            if not dry_run and (state.get("last_decision") or {}).get("target", {}).get("kind") != "refused":
                events.record("refused", "private inference: no box available, cloud refused")
            state["last_decision"] = decision
            store.save_state({**store.load_state(), "last_decision": decision})
            return decision
        if target["kind"] == "cloud" and not _cloud_ready(target):
            decision["applied"] = False
            decision["warning"] = ("no cloud target set (hermes fleet setup, or "
                                   "settings cloud_provider + cloud_model); primary left as is")
            store.update_state(last_decision=decision)
            return decision
        changed = decision["changed"]
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
        elif not dry_run and state.get("applied"):
            # Same box as before, so the config is not rewritten; the pin is policy and still changes.
            if pin and target.get("node_id") == current["node_id"]:
                state["applied"]["pinned"] = True
            elif unpin:
                state["applied"].pop("pinned", None)
        if not dry_run and not settings.get("private_only") and _cloud_ready({"provider": settings.get("cloud_provider"),
                                                                               "model": settings.get("cloud_model")}):
            entry = {"provider": settings["cloud_provider"], "model": settings["cloud_model"]}
            if state.get("fallback_ensured") == entry and not config_write.has_fallback(
                    config_write.fallback_chain(), entry["provider"], entry["model"]):
                pass  # removed by someone else since we added it: drift, never silently re-added
            else:
                decision["fallback_added"] = config_write.ensure_fallback(entry["provider"], entry["model"])
                state["fallback_ensured"] = entry
        if not dry_run:
            decision["keep"] = _keep_loaded(settings, f, results, applied_now, state.get("applied") or {})
        if not dry_run or aux_follow:  # side tasks are their own opt-in, independent of main routing
            decision["aux"] = _follow_aux(settings, f, results, decision, state)
        if state.get("paused"):
            decision["warning"] = ("Hermes's primary was changed outside Local Fleet, so routing is paused; "
                                   "Auto-pick box or `hermes fleet use --best` resumes it")
        state["last_decision"] = decision
        if decision["applied"]:
            t = decision["target"]
            events.record("route", (f"{t.get('node_name')} · {t.get('model')}" if t["kind"] == "local"
                                    else f"cloud · {t.get('provider')}/{t.get('model')}"), reason=decision["reason"],
                          via=t.get("via"))
        if decision.get("aux") and "→" in decision["aux"]:
            events.record("aux", decision["aux"])
        if decision["applied"]:
            event = {"at": decision["at"], "reason": decision["reason"], "kind": target["kind"],
                     "node": target.get("node_name"), "model": target.get("model"), "via": target.get("via")}
            state["history"] = ((store.load_state().get("history") or []) + [event])[-HISTORY_LEN:]
        merged = {**store.load_state(), **state}
        if not state.get("paused"):
            merged.pop("paused", None)
        store.save_state(merged)
        return decision


def _follow_aux(settings, f, results, decision, state) -> str | None:
    """Keep the auxiliary tasks on the freest healthy box (whatever the mode), or put the user's own
    blocks back when no box is healthy. Writes only when the target changes. Updates `state`."""
    tasks = list(settings.get("aux_tasks") or [])
    current = state.get("aux_applied")
    if not tasks or state.get("aux_paused"):
        return None
    if current and _aux_drift(current):
        state["aux_paused"] = True
        events.record("drift", "side-task settings were changed outside Local Fleet; it stopped moving them")
        return "side tasks changed outside Local Fleet: paused (reapply or relinquish)"
    # A task holding a literal api_key is the user's own secret: leave it alone, so the key is never
    # copied into Local Fleet's state (aux_original) and never travels to another host.
    aux_cfg = (config_write._load().get("auxiliary") or {})
    keyed = [t for t in tasks if (aux_cfg.get(t) or {}).get("api_key") and t not in ((current or {}).get("tasks") or [])]
    tasks = [t for t in tasks if t not in keyed]
    note = f" (left {', '.join(keyed)} alone: it has its own API key)" if keyed else ""
    if not tasks:
        return f"side tasks: none moved{note}" if keyed else None
    # Least busy healthy box that needs no key (auxiliary blocks cannot name a key's env var).
    want_model = decision.get("tier_model") or ""
    excluded = state.get("exclusions") or {}
    min_ctx = int(settings.get("min_context") or readiness.DEFAULT_MIN_CONTEXT)
    keyless = [n for n in f.enabled() if not n.get("api_key_env")
               and check(n, results.get(n["id"]), want_model, excluded, min_ctx)[0]]
    node = min(keyless, key=lambda n: score(n, results[n["id"]], settings.get("prefer_labels") or (), want_model),
               default=None)
    if node is None:
        if current:
            aux.apply(current["tasks"], None, state.get("aux_original") or {})
            state["aux_applied"] = None
            return "no healthy box: side tasks back on their own settings"
        return None
    model = model_for(node, results.get(node["id"]) or {}, decision.get("tier_model") or "")
    want = {"tasks": tasks, "node_id": node["id"], "node_name": node["name"], "model": model}
    if current == want:
        return f"side tasks unchanged{note}" if keyed else None
    private = bool(settings.get("private_only"))
    before = aux.apply(tasks, aux.block(node, model, None if private else settings.get("cloud_provider"),
                                        None if private else settings.get("cloud_model")), None)
    original = state.get("aux_original") or {}
    for t in tasks:
        original.setdefault(t, before.get(t, {}))
    state["aux_original"] = original
    state["aux_applied"] = want
    return f"side tasks → {node['name']} · {model}{note}"


FOREVER = -1     # Ollama keep_alive: never unload (a number: "-1" as text is rejected, it has no unit)
RELEASE = "5m"   # back to a normal idle timer


def _keep_loaded(settings, f, results, before: dict, now: dict) -> str | None:
    """With keep_loaded on, hold the routed model in memory; release the previous box's model
    when routing moves. Only Ollama boxes; never raises."""
    try:
        moved = before.get("kind") == "local" and (before.get("node_id"), before.get("model")) != (now.get("node_id"), now.get("model"))
        if moved or (before and not settings.get("keep_loaded")):
            old = f.find(before.get("node_id") or "")
            if old is not None and before.get("model") and before.get("kept"):
                warm(old, before["model"], [before["model"]], timeout=10, keep_alive=RELEASE, refresh=True)
        if not settings.get("keep_loaded") or now.get("kind") != "local":
            now.pop("kept", None)
            return None
        node = f.find(now.get("node_id") or "")
        snap = results.get(now.get("node_id")) or {}
        if node is None or node.get("kind") != "ollama":
            return None
        expires = (snap.get("expires") or {}).get(now["model"], "")
        if now["model"] in (snap.get("resident") or []) and expires[:4] >= "2100":
            now["kept"] = True
            return None  # already held
        r = warm(node, now["model"], snap.get("resident") or [], timeout=float(settings.get("warm_timeout_s") or 120),
                 keep_alive=FOREVER, refresh=True)
        now["kept"] = True
        return f"keeping {now['model']} loaded on {node['name']}" + ("" if r.get("warmed") else f" ({r.get('detail')})")
    except Exception:
        return None


def exclude(ref: str, kind: str, minutes: float | None = None) -> dict:
    """Leave a box out of selection: kind "rehearsal" (a simulated outage inside Local Fleet only,
    expiring after `minutes`) or "maintenance" (until turned off). Nothing is stopped on the box and
    requests already running there finish. Re-routes only if routing is on."""
    with store.transaction():
        node = store.fleet().get(ref)
        state = store.load_state()
        until = (datetime.now(timezone.utc) + timedelta(minutes=minutes or 10)).isoformat(timespec="seconds") \
            if kind == "rehearsal" else None
        state.setdefault("exclusions", {})[node["id"]] = {"kind": kind, "until": until, "since": now_iso(),
                                                          "label": node.get("title") or node["name"]}
        store.save_state(state)
    label = node.get("title") or node["name"]
    events.record(kind, f"{label}: simulated outage for {int(minutes or 10)} min (nothing stopped on the box)"
                  if kind == "rehearsal" else f"{label}: maintenance on, left out of new selections", box=node["name"])
    return apply_policy(dry_run=not store.load_state().get("applied"))


def include(ref: str) -> dict:
    """End a rehearsal or maintenance for a box."""
    with store.transaction():
        node = store.fleet().get(ref)
        state = store.load_state()
        ex = (state.get("exclusions") or {}).pop(node["id"], None)
        store.save_state(state)
    if ex:
        events.record(ex.get("kind", "rehearsal"), f"{node.get('title') or node['name']}: back in selection", box=node["name"])
    return apply_policy(dry_run=not store.load_state().get("applied"))


def set_private(on: bool) -> str:
    """Private inference on: cloud entries come off fallback_providers (kept to put back), side
    tasks lose their cloud fallback, subagents refuse cloud, and with no box available Local Fleet
    refuses instead of switching to cloud. Off: the entries go back."""
    local_urls = {config_write._norm(n["base_url"]) for n in store.fleet().nodes}
    with store.transaction():
        state = store.load_state()
        if on:
            removed = config_write.remove_non_local_fallbacks(local_urls)
            state["private_removed"] = (state.get("private_removed") or []) + removed
            state["aux_applied"] = state.get("aux_applied") and {**state["aux_applied"], "model": None}  # re-apply without cloud
        else:
            config_write.restore_fallbacks(state.pop("private_removed", None) or [])
        store.save_state(state)
    store.write_setting("private_only", on)
    events.record("private", "private inference on: cloud refused" if on else "private inference off: cloud fallback restored")
    d = apply_policy(dry_run=not store.load_state().get("applied"), aux_follow=True)
    n = len(state.get("private_removed") or []) if on else 0
    return (f"private inference on: {n} cloud fallback entr{'y' if n == 1 else 'ies'} taken off (restored when off). "
            "Only Hermes's model calls are covered; tools such as web search still use the internet." if on
            else "private inference off: cloud fallback entries restored") + (f"\n{d.get('warning')}" if d.get("warning") else "")


def set_keep(on: bool) -> str:
    """Turn keep_loaded on (holds the routed model now) or off (hands it back to Ollama's timer)."""
    store.write_setting("keep_loaded", on)
    with store.transaction():
        state = store.load_state()
        applied = state.get("applied") or {}
        if not applied:
            return "on; takes effect once Hermes is routed to a box" if on else "off"
        settings, f, results = probe()
        before = dict(applied)
        msg = _keep_loaded(settings, f, results, before, applied)
        state["applied"] = applied
        store.save_state({**store.load_state(), "applied": applied})
        return msg or ("on" if on else "off; the model unloads after Ollama's normal idle time")


def aux_off() -> list[str]:
    with store.transaction():
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
    with store.transaction():
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
        "model_tiers": [m for m in model_tiers(settings) if m],
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
        "keep_loaded": bool(settings.get("keep_loaded")),
        "hide_addresses": bool(settings.get("hide_addresses")),
        "private_only": bool(settings.get("private_only")),
        "paused": bool(state.get("paused")),
        "exclusions": {k: v for k, v in (state.get("exclusions") or {}).items()},
        "events": events.timeline(40),
        "drift": drift(state),
        "delegation_backend": store.delegation_backend(),
        "delegations": (state.get("delegations") or [])[-10:],
        "history": state.get("history") or [],
        "fallback_chain": [{k: e.get(k) for k in ("provider", "model")} for e in config_write.fallback_chain()
                           if isinstance(e, dict)],
    }
