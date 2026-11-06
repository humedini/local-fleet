"""Routing policy: which backend should be Hermes's primary model right now.

`decide()` is pure (nodes + probe results + settings + what is applied now -> a decision), so
the whole mode matrix is unit-tested without a network or a Hermes install. `apply()` writes a
decision into Hermes's own config through config_write, and only when it differs from what is
already there: rewriting an unchanged primary would cost the user nothing but churn.

The plugin chooses the primary. The cloud backup chain stays Hermes's own `fallback_providers`,
which handles per-turn failover and restores the primary next turn; this module only makes
sure the user's cloud entry is on that list.
"""
from __future__ import annotations

from datetime import datetime

from .fleet import now_iso
from .health import routable, score
from .readiness import DEFAULT_MIN_CONTEXT, verdict


def _usable_models(snap: dict) -> list[str]:
    return [m for m in snap.get("models", []) if "embed" not in m.lower()]


def model_for(node: dict, snap: dict, want: str, current_model: str = "") -> str:
    """The model to run on `node`: the configured one, else keep the current one if served,
    else one already in memory, else the first chat model it lists."""
    if want:
        return want
    usable = _usable_models(snap)
    if current_model in usable:
        return current_model
    for m in snap.get("resident", []):
        if m in usable:
            return m
    return usable[0] if usable else ""


def _local(node, snap, want, current, reason):
    return {
        "kind": "local",
        "node_id": node["id"],
        "node_name": node["name"],
        "base_url": node["base_url"],
        "model": model_for(node, snap, want, current.get("model", "")),
        "reason": reason,
    }


def _cloud(settings, reason):
    return {
        "kind": "cloud",
        "provider": settings.get("cloud_provider") or "",
        "model": settings.get("cloud_model") or "",
        "reason": reason,
    }


def _hhmm(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M") if iso else ""
    except ValueError:
        return ""


def check(node: dict, snap: dict | None, want: str, excluded: dict | None = None,
          min_context: int = DEFAULT_MIN_CONTEXT) -> tuple[bool, str]:
    """(eligible, reason) for one box and model: the single eligibility rule the main route,
    subagents and side tasks all use, and what the decision inspector shows."""
    if not node.get("enabled", True):
        return False, "disabled"
    ex = (excluded or {}).get(node["id"])
    if ex:
        if ex.get("kind") == "maintenance":
            return False, "maintenance: left out of new selections"
        return False, f"simulated outage (rehearsal) until {_hhmm(ex.get('until'))}"
    if not snap or snap.get("status") not in ("ok", "degraded"):
        return False, f"down: {(snap or {}).get('detail') or 'not probed'}"
    if not routable(node, snap, want):
        return False, f"does not have {want}"
    return verdict((node.get("caps") or {}).get(want), min_context)


def _refused(nodes, results, want, current) -> dict:
    """Private inference with no box available: refuse cloud, and hold the primary on a registered box
    (the one Hermes is on, else one that has the model, else the first enabled) so Hermes's calls fail
    rather than reach cloud, and resume there by themselves when it is back."""
    enabled = [n for n in nodes if n.get("enabled", True)]
    hold = (next((n for n in enabled if current.get("kind") in ("local", "refused") and n["id"] == current.get("node_id")), None)
            or next((n for n in enabled if want and want in ((results.get(n["id"]) or {}).get("models") or [])), None)
            or (enabled[0] if enabled else None))
    t = {"kind": "refused", "reason": "private inference: no registered box available, so Local Fleet refuses cloud; "
                                      "Hermes's calls fail until a box is back"}
    if hold is not None:
        model = want or (current.get("model") if current.get("node_id") == hold["id"] else "") or ""
        t.update({"node_id": hold["id"], "node_name": hold["name"], "base_url": hold["base_url"], "model": model})
    return t


def _keep_current(current, nodes, results, freest, want, settings, ok) -> bool:
    """Stay on a healthy active node unless the freest is more than switch_margin freer."""
    if current.get("kind") != "local":
        return False
    node = next((n for n in nodes if n["id"] == current.get("node_id")), None)
    if node is None or not ok(node, want):
        return False
    if node["id"] == freest["id"]:
        return True
    margin = float(settings.get("switch_margin", 0.25))
    cur = score(node, results[node["id"]], settings.get("prefer_labels") or ())
    best = score(freest, results[freest["id"]], settings.get("prefer_labels") or ())
    return cur[1] - best[1] <= margin


def model_tiers(settings: dict) -> list[str]:
    """The local models in order of preference: the main one, then `fallback_models`.
    [""] when no model is set (any box, its own model)."""
    tiers = [settings.get("default_model") or ""] + [m for m in (settings.get("fallback_models") or []) if m]
    out = []
    for m in tiers:
        if m not in out:
            out.append(m)
    return out if out[0] else [""]


def choose_tier(nodes: list[dict], results: dict[str, dict], settings: dict,
                excluded: dict | None = None) -> tuple[str, int]:
    """(model, tier index) of the first tier some eligible box can serve; tier 0 if none."""
    tiers = model_tiers(settings)
    min_ctx = int(settings.get("min_context") or DEFAULT_MIN_CONTEXT)
    for i, m in enumerate(tiers):
        if any(check(n, results.get(n["id"]), m, excluded, min_ctx)[0] for n in nodes):
            return m, i
    return tiers[0], 0


def decide(settings: dict, nodes: list[dict], results: dict[str, dict], current: dict,
           excluded: dict | None = None) -> dict:
    """Return a decision: {"target": {...}, "reason", "candidates", "freest_node_id", ...}.

    `current` is what the plugin last applied ({} if nothing): {"kind", "node_id", "model",
    "via", "pinned"}. `via` is "failover" when cloud was applied because every local was down.
    `excluded` holds boxes left out by rehearsal or maintenance. `candidates` records, for every
    box, whether it was eligible, why, and its score: what the decision inspector shows.
    """
    mode = settings.get("mode", "auto")
    labels = settings.get("prefer_labels") or ()
    min_ctx = int(settings.get("min_context") or DEFAULT_MIN_CONTEXT)
    want, tier = choose_tier(nodes, results, settings, excluded)
    verdicts = {n["id"]: check(n, results.get(n["id"]), want, excluded, min_ctx) for n in nodes}
    ok = lambda n, m: check(n, results.get(n["id"]), m, excluded, min_ctx)[0]  # noqa: E731
    healthy = [n for n in nodes if verdicts[n["id"]][0]]
    freest = min(healthy, key=lambda n: score(n, results[n["id"]], labels, want), default=None)
    note = f" (fallback model {want})" if tier else ""

    pinned_node = next((n for n in nodes if current.get("pinned") and n["id"] == current.get("node_id")), None)
    pin_model = next((m for m in model_tiers(settings) if pinned_node and ok(pinned_node, m)), None)
    if pinned_node is not None and pin_model is not None:
        target = _local(pinned_node, results[pinned_node["id"]], pin_model, current, f"kept on {pinned_node['name']} (you chose it)")
    elif mode == "prefer-cloud" and not settings.get("private_only"):
        target = _cloud(settings, "prefer-cloud mode")
    elif freest is None and settings.get("private_only"):
        target = _refused(nodes, results, want, current)
    elif freest is None:
        why = (f"no box available with {' or '.join(model_tiers(settings))}" if want and nodes
               else "no box available")
        target = _cloud(settings, f"{why}, using cloud")
        target["via"] = "failover"
    elif (current.get("kind") == "cloud" and current.get("via") == "failover"
          and not settings.get("failback_enabled", True) and not settings.get("private_only")):
        target = _cloud(settings, f"{freest['name']} is back, but switching back is off")
        target["via"] = "failover"
    elif _keep_current(current, nodes, results, freest, want, settings, ok):
        node = next(n for n in nodes if n["id"] == current["node_id"])
        target = _local(node, results[node["id"]], want, current, f"staying on {node['name']}{note}")
    else:
        back = current.get("kind") == "cloud" and current.get("via") == "failover"
        upgraded = (current.get("kind") == "local" and current.get("model") and current.get("model") != want
                    and tier == 0 and want)
        reason = (f"back on {freest['name']} (it recovered)" if back
                  else f"back to your main model on {freest['name']}" if upgraded
                  else f"least busy box: {freest['name']}")
        target = _local(freest, results[freest["id"]], want, current, reason + note)

    return {
        "at": now_iso(),
        "mode": mode,
        "target": target,
        "reason": target["reason"],
        "healthy_locals": [n["name"] for n in healthy],
        "freest_node_id": freest["id"] if freest else None,
        "tier": tier,
        "tier_model": want,
        "pinned": bool(current.get("pinned")),
        "candidates": _candidates(nodes, results, verdicts, labels, want, target, freest),
        "changed": not same_target(target, current),
    }


def _candidates(nodes, results, verdicts, labels, want, target, freest) -> list[dict]:
    """Every box with its verdict and the numbers behind the score, eligible ones best first."""
    out = []
    for n in nodes:
        snap = results.get(n["id"]) or {}
        eligible, reason = verdicts[n["id"]]
        perf = n.get("perf") or {}
        out.append({
            "id": n["id"], "name": n["name"], "title": n.get("title"), "eligible": eligible, "reason": reason,
            "status": snap.get("status"), "load": snap.get("load_proxy"), "latency_ms": snap.get("latency_ms"),
            "free_bytes": snap.get("free_vram_approx"), "checked_at": snap.get("checked_at"),
            "tps": perf.get("tps") if perf.get("model") == want else None,
            "chosen": target.get("kind") == "local" and target.get("node_id") == n["id"],
            "least_busy": bool(freest and freest["id"] == n["id"]),
            "score": list(score(n, snap, labels, want)[1:5]) if eligible else None,
        })
    out.sort(key=lambda c: (not c["eligible"], c["score"] or [9, 9, 9, 9]))
    return out


def same_target(target: dict, current: dict) -> bool:
    if target.get("kind") != current.get("kind"):
        return False
    if target["kind"] in ("local", "refused"):
        return (target.get("node_id"), target.get("model")) == (current.get("node_id"), current.get("model"))
    return (target.get("provider"), target.get("model")) == (current.get("provider"), current.get("model"))
