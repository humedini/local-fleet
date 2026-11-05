"""Plain-text views shared by the CLI and `/fleet` (they return text; nothing here prints)."""
from __future__ import annotations


def _load(h: dict, perf: dict | None = None) -> str:
    bits = []
    if perf and perf.get("tps"):
        bits.append(f"{perf['tps']:g}t/s")
    if h.get("latency_ms") is not None:
        bits.append(f"{h['latency_ms']}ms")
    if h.get("load_proxy") is not None:
        bits.append(f"load={h['load_proxy']:g}")
    if h.get("free_vram_approx"):
        bits.append(f"free={h['free_vram_approx'] / 1e9:.0f}GB")
    return " ".join(bits)


def node_line(node: dict, active_id: str = "", freest_id: str = "") -> str:
    h = node.get("last_health") or {}
    status = h.get("status", "unprobed") if node.get("enabled", True) else "disabled"
    perf = node.get("perf")
    marks = ("  ← active" if node["id"] == active_id else "") + ("  (least busy)" if node["id"] == freest_id else "")
    detail = h.get("detail", "") if h.get("detail") not in (None, "ok") else ""
    detail = detail.replace("ok · fallback ", "fallback · ")
    return (f"  {node['name']:<12} {status:<9} {_load(h, perf):<30} {node['kind']:<17} {node['base_url']}"
            f"{'  ' + detail if detail else ''}{marks}").rstrip()


def nodes_table(nodes: list[dict], active_id: str = "", freest_id: str = "") -> str:
    if not nodes:
        return "No nodes yet. Add one: hermes fleet add --name gx10 --url http://192.168.1.50:11434/v1 --kind ollama"
    head = f"  {'name':<12} {'status':<9} {'health':<30} {'kind':<17} url"
    return "\n".join([head] + [node_line(n, active_id, freest_id) for n in nodes])


def target_text(t: dict) -> str:
    if not t:
        return "nothing applied yet"
    if t.get("kind") == "local":
        return f"{t.get('node_name')} · {t.get('model') or '?'} · {t.get('base_url')}"
    return f"cloud · {t.get('provider') or '?'}/{t.get('model') or '?'}"


def decision_text(d: dict) -> str:
    lines = [f"mode: {d.get('mode')}", f"route: {target_text(d.get('target') or {})}",
             f"why: {d.get('reason')}"]
    if d.get("applied"):
        lines.append("applied: primary model updated (gateway and Desktop pick it up on the next message; "
                     "a running CLI session on its next session)")
    elif d.get("changed") is False:
        lines.append("applied: already the primary, nothing to change")
    if d.get("fallback_added"):
        lines.append("fallback_providers: cloud entry added")
    if d.get("warning"):
        lines.append(f"warning: {d['warning']}")
    return "\n".join(lines)


def status_text(fleet_nodes: list[dict], decision: dict, active_id: str = "") -> str:
    """`active_id` is the node Hermes is routed to now (from state), not the decision's pick."""
    return nodes_table(fleet_nodes, active_id, decision.get("freest_node_id") or "") + "\n\n" + decision_text(decision)
