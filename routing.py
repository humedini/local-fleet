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

from .fleet import now_iso
from .health import pick_freest, routable, score


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


def _keep_current(current, nodes, results, freest, want, settings) -> bool:
    """Stay on a healthy active node unless the freest is more than switch_margin freer."""
    if current.get("kind") != "local":
        return False
    node = next((n for n in nodes if n["id"] == current.get("node_id")), None)
    if node is None or not routable(node, results.get(node["id"]), want):
        return False
    if node["id"] == freest["id"]:
        return True
    margin = float(settings.get("switch_margin", 0.25))
    cur = score(node, results[node["id"]], settings.get("prefer_labels") or ())
    best = score(freest, results[freest["id"]], settings.get("prefer_labels") or ())
    return cur[1] - best[1] <= margin


def decide(settings: dict, nodes: list[dict], results: dict[str, dict], current: dict) -> dict:
    """Return a decision: {"target": {...}, "reason", "healthy_locals", "freest_node_id", ...}.

    `current` is what the plugin last applied ({} if nothing): {"kind", "node_id", "model",
    "via", "pinned"}. `via` is "failover" when cloud was applied because every local was down.
    """
    mode = settings.get("mode", "auto")
    want = settings.get("default_model") or ""
    labels = settings.get("prefer_labels") or ()
    enabled = [n for n in nodes if n.get("enabled", True)]
    healthy = [n for n in enabled if routable(n, results.get(n["id"]), want)]
    freest = pick_freest(enabled, results, want, labels)

    pinned = next((n for n in healthy if current.get("pinned") and n["id"] == current.get("node_id")), None)
    if pinned is not None:
        target = _local(pinned, results[pinned["id"]], want, current, f"kept on {pinned['name']} (you chose it)")
    elif mode == "prefer-cloud":
        target = _cloud(settings, "prefer-cloud mode")
    elif freest is None:
        why = f"no box available with {want}" if want and enabled else "no box available"
        target = _cloud(settings, f"{why}, using cloud")
        target["via"] = "failover"
    elif (current.get("kind") == "cloud" and current.get("via") == "failover"
          and not settings.get("failback_enabled", True)):
        target = _cloud(settings, f"{freest['name']} is back, but switching back is off")
        target["via"] = "failover"
    elif _keep_current(current, enabled, results, freest, want, settings):
        node = next(n for n in enabled if n["id"] == current["node_id"])
        target = _local(node, results[node["id"]], want, current, f"staying on {node['name']}")
    else:
        back = current.get("kind") == "cloud" and current.get("via") == "failover"
        target = _local(freest, results[freest["id"]], want, current,
                        f"back on {freest['name']} (it recovered)" if back else f"least busy box: {freest['name']}")

    return {
        "at": now_iso(),
        "mode": mode,
        "target": target,
        "reason": target["reason"],
        "healthy_locals": [n["name"] for n in healthy],
        "freest_node_id": freest["id"] if freest else None,
        "changed": not same_target(target, current),
    }


def same_target(target: dict, current: dict) -> bool:
    if target.get("kind") != current.get("kind"):
        return False
    if target["kind"] == "local":
        return (target.get("node_id"), target.get("model")) == (current.get("node_id"), current.get("model"))
    return (target.get("provider"), target.get("model")) == (current.get("provider"), current.get("model"))
