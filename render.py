"""Plain-text views shared by the CLI and `/fleet` (they return text; nothing here prints).
Everything that can show an address goes through `_url`, `redact` or `strip_addresses`, which honour
the privacy setting (HIDE, set by the CLI and /fleet from `hide_addresses`)."""
from __future__ import annotations

import re


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


HIDE = {"on": False, "hosts": ()}  # set by every output path from the hide_addresses setting (see configure)


_ADDR = re.compile(r"(?:https?://|\b)(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?[^\s'\"()<>,;]*|https?://[^\s'\"()<>,;]+"
                   r"|\b[\w-]+(?:\.[\w-]+)*\.(?:ts\.net|local|lan|home|internal|home\.arpa)(?::\d+)?[^\s'\"()<>,;]*"
                   r"|\b[A-Za-z][\w-]*(?:\.[\w-]+)*:\d{2,5}\b|\[[0-9a-fA-F:]+\](?::\d+)?")


def hosts_of(nodes) -> tuple[str, ...]:
    """The host part of every registered box's URL, longest first (redacted wherever it appears).
    A host that is also a box's name (http://gx10:11434 registered as gx10) stays: the name is shown
    on purpose, and masking it would hide the box itself."""
    from urllib.parse import urlsplit
    nodes = list(nodes or [])
    names = {str(v).lower() for n in nodes for v in (n.get("name"), n.get("title")) if v}
    out = {(urlsplit(n.get("base_url") or "").hostname or "") for n in nodes}
    return tuple(sorted((h for h in out if len(h) > 2 and h.lower() not in names), key=len, reverse=True))


def configure(on: bool, nodes=()) -> None:
    """Turn address hiding on or off for this process's output, knowing the boxes' own hosts."""
    HIDE["on"] = bool(on)
    HIDE["hosts"] = hosts_of(nodes) if on else ()


def mask(text: str, hosts=()) -> str:
    """Always: URLs, IP addresses, host:port, LAN/tailnet names and the boxes' own hosts -> <address>."""
    out = _ADDR.sub("<address>", str(text))
    for h in hosts:
        out = re.sub(rf"(?<![\w.-]){re.escape(h)}(?![\w-])", "<address>", out)
    return out


def redact(text: str) -> str:
    """With privacy on, any address in `text` becomes <address>."""
    return mask(text, HIDE["hosts"]) if HIDE["on"] else str(text)


_ADDRESS_KEYS = {"base_url", "url", "api", "origin"}


def strip_addresses(v):
    """With privacy on, drop every address field and redact addresses in strings, recursively."""
    if not HIDE["on"]:
        return v
    if isinstance(v, dict):
        return {k: strip_addresses(x) for k, x in v.items() if k not in _ADDRESS_KEYS}
    if isinstance(v, list):
        return [strip_addresses(x) for x in v]
    return redact(v) if isinstance(v, str) else v


def scrub(v, on: bool, nodes=()):
    """`strip_addresses` for one value with an explicit setting: what the Desktop REST, the agent
    tools and the JSON export send (they run in long-lived processes, so no global switch)."""
    if not on:
        return v
    saved = dict(HIDE)
    try:
        configure(True, nodes)
        return strip_addresses(v)
    finally:
        HIDE.update(saved)


def _url(node: dict) -> str:
    return "(address hidden)" if HIDE["on"] else node["base_url"]


def node_line(node: dict, active_id: str = "", freest_id: str = "") -> str:
    h = node.get("last_health") or {}
    status = h.get("status", "unprobed") if node.get("enabled", True) else "disabled"
    perf = node.get("perf")
    marks = ("  ← active" if node["id"] == active_id else "") + ("  (least busy)" if node["id"] == freest_id else "")
    detail = h.get("detail", "") if h.get("detail") not in (None, "ok") else ""
    detail = redact(detail.replace("ok · fallback ", "fallback · "))
    name = node["name"] + ("*" if node.get("members") else "")
    return (f"  {name:<12} {status:<9} {_load(h, perf):<30} {node['kind']:<17} {_url(node)}"
            f"{'  ' + detail if detail else ''}{marks}").rstrip()


def nodes_table(nodes: list[dict], active_id: str = "", freest_id: str = "") -> str:
    if not nodes:
        return "No nodes yet. Add one: hermes fleet add --name gx10 --url http://192.168.1.50:11434/v1 --kind ollama"
    head = f"  {'name':<12} {'status':<9} {'health':<30} {'kind':<17} url"
    return "\n".join([head] + [node_line(n, active_id, freest_id) for n in nodes])


def target_text(t: dict) -> str:
    if not t:
        return "nothing applied yet"
    if t.get("kind") == "refused":
        return f"refused (private inference)" + (f": primary held on {t.get('node_name')}" if t.get("node_name") else "")
    if t.get("kind") == "local":
        return f"{t.get('node_name')} · {t.get('model') or '?'}" + ("" if HIDE["on"] else f" · {t.get('base_url')}")
    return f"cloud · {t.get('provider') or '?'}/{t.get('model') or '?'}"


def decision_text(d: dict) -> str:
    lines = [f"mode: {d.get('mode')}", f"route: {target_text(d.get('target') or {})}",
             f"why: {redact(d.get('reason'))}"]
    if d.get("applied"):
        lines.append("applied: primary model updated (gateway and Desktop pick it up on the next message; "
                     "a running CLI session on its next session)")
    elif d.get("changed") is False:
        lines.append("applied: already the primary, nothing to change")
    if d.get("fallback_added"):
        lines.append("fallback_providers: cloud entry added")
    if d.get("warning"):
        lines.append(f"warning: {redact(d['warning'])}")
    return "\n".join(lines)


def why_text(d: dict) -> str:
    """The decision inspector as text: what was picked, why, and every box's verdict."""
    t = d.get("target") or {}
    lines = [f"route: {target_text(t)}", f"why: {redact(d.get('reason'))}",
             f"mode: {d.get('mode')}{' · pinned' if d.get('pinned') else ''} · model tier: {d.get('tier_model') or '(each box its own)'}"
             + (f" (fallback tier {d.get('tier')})" if d.get("tier") else ""), "",
             f"  {'box':<14} {'verdict':<9} {'load':>5} {'latency':>8} {'tok/s':>6}  reason"]
    for c in d.get("candidates") or []:
        mark = "→ " if c.get("chosen") else "  "
        load = "-" if c.get("load") is None else f"{c['load']:.2f}"
        lat = "-" if c.get("latency_ms") is None else f"{c['latency_ms']}ms"
        lines.append(f"{mark}{(c.get('title') or c['name'])[:14]:<14} {'eligible' if c['eligible'] else 'out':<9} {load:>5} {lat:>8} "
                     f"{c.get('tps') or '-':>6}  {redact(c['reason'])}{'  (least busy)' if c.get('least_busy') else ''}")
    lines.append("\nScore order: load, then preferred labels, then speed on this model, then free memory, then latency.")
    return "\n".join(lines)


def events_text(items: list[dict]) -> str:
    from datetime import datetime
    if not items:
        return "no events yet"
    out = []
    for e in items:
        when = datetime.fromtimestamp(e.get("t", 0)).strftime("%a %H:%M:%S")
        out.append(f"  {when}  {e.get('kind', ''):<12} {redact(e.get('text', ''))}{' · ' + redact(e['reason']) if e.get('reason') else ''}")
    return "\n".join(out)


def readiness_text(nodes: list[dict], tiers: list[str], min_context: int) -> str:
    from .readiness import verdict
    yn = {True: "yes", False: "NO", None: "?"}
    lines = [f"  {'box':<14} {'model':<24} {'has':<4} {'tools':<6} {'vision':<7} {'context':<26} verdict"]
    for n in nodes:
        models = (n.get("last_health") or {}).get("models") or []
        for m in tiers:
            c = (n.get("caps") or {}).get(m) or {}
            have = m in models
            ok, why = verdict(c, min_context) if have else (None, "not installed")
            ctx = f"{c['context']} ({c.get('context_source')})" if c.get("context") else (c.get("context_source") or "?")
            lines.append(f"  {(n.get('title') or n['name'])[:14]:<14} {m[:24]:<24} {'yes' if have else 'no':<4} "
                         f"{yn.get(c.get('tools')):<6} {yn.get(c.get('vision')):<7} {ctx[:26]:<26} {'-' if ok is None else 'ok' if ok else 'REJECTED'}: {why}")
    lines.append(f"\nEvidence: Ollama /api/show (capabilities, num_ctx) and /api/ps (running context). Minimum context {min_context}.")
    return "\n".join(lines)


def status_text(fleet_nodes: list[dict], decision: dict, active_id: str = "") -> str:
    """`active_id` is the node Hermes is routed to now (from state), not the decision's pick."""
    return nodes_table(fleet_nodes, active_id, decision.get("freest_node_id") or "") + "\n\n" + decision_text(decision)
