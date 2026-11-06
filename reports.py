"""Shareable exports: the incident card (flight recorder as Markdown) and the savings receipt.

Both are meant to be pasted into chat, Notion or a PR, so they are always scrubbed with the same
filter privacy mode uses (render.mask with the boxes' own hosts), whatever the privacy setting.
They describe; they never change routing. "Configured" (what Local Fleet set) and "served" (what
Hermes's per-call hooks saw answer) are kept apart, and simulations are labelled as such.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import events, pricing, store, traffic
from .render import hosts_of, mask

ROOT = Path(__file__).resolve().parent
SIMULATED = {"rehearsal", "pack"}


def version() -> str:
    try:
        for line in (ROOT / "plugin.yaml").read_text().splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "?"


def _sha() -> str:
    head = ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (ROOT / ".git" / ref[5:]).read_text().strip()[:7]
        return ref[:7]
    except OSError:
        return ""


def _when(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%a %d %b %H:%M:%S")


def incident_card(hours: float = 24, now: float | None = None) -> str:
    """The recorder over the last `hours` as a Markdown card."""
    now = now or time.time()
    hosts = hosts_of(store.fleet().nodes)
    items = [e for e in events.timeline(400) if e.get("t", 0) >= now - hours * 3600]
    stamp = f"Local Fleet {version()}" + (f" ({_sha()})" if _sha() else "")
    if not items:
        return f"### Local Fleet incident card\n\nNothing recorded in the last {hours:g} h.\n\n_{stamp}_\n"
    sim = [e for e in items if e.get("kind") in SIMULATED]
    real_down = [e for e in items if e.get("kind") == "health" and "went down" in e.get("text", "")]
    routes = [e for e in items if e.get("kind") == "route"]
    served = [e for e in items if e.get("kind") == "served"]
    path = []
    for e in routes:
        hop = "cloud" if e.get("text", "").startswith("cloud") else e.get("text", "").split(" · ")[0]
        if not path or path[-1] != hop:
            path.append(hop)
    lines = ["### Local Fleet incident card", "",
             f"- **Window:** {_when(items[0]['t'])} to {_when(items[-1]['t'])} ({len(items)} events)",
             f"- **Simulated:** {'yes, ' + str(len(sim)) + ' rehearsal events (nothing was stopped on any box)' if sim else 'no'}",
             f"- **Real outages:** {len(real_down)}",
             f"- **Configured route:** {' → '.join(mask(p, hosts) for p in path) if path else 'unchanged'}",
             f"- **Served (from Hermes's per-call hooks):** " + (", ".join(mask(e['text'], hosts) for e in served[-4:]) if served
                                                                 else "no calls recorded in this window, so nothing here proves what answered"),
             "", "| When | Kind | What |", "|---|---|---|"]
    for e in items[-30:]:
        kind = e.get("kind", "") + (" (simulated)" if e.get("kind") in SIMULATED else "")
        what = mask(e.get("text", ""), hosts) + (f" · {mask(e['reason'], hosts)}" if e.get("reason") else "")
        lines.append(f"| {_when(e['t'])} | {kind} | {what.replace('|', '/')} |")
    lines += ["", "_Configured is what Local Fleet set; served is what actually answered. Addresses removed. " + stamp + "_"]
    return "\n".join(lines) + "\n"


def _window(lines: list[dict], window: str, now: float) -> tuple[list[dict], str]:
    if window == "today":
        start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return [ln for ln in lines if ln.get("t", 0) >= start], "today"
    return [ln for ln in lines if ln.get("t", 0) >= now - 7 * 86400], "the last 7 days"


def savings_receipt(window: str = "today", now: float | None = None) -> tuple[str, dict]:
    """(Markdown, JSON) for spend avoided over `window` ("today" or "week"), with its working."""
    now = now or time.time()
    settings = store.read_settings()
    eff = pricing.effective(settings, store.load_state().get("auto_price"))
    lines, label = _window(traffic.load(8 * 86400), window, now)
    t = traffic.summarize(lines, (eff["in"], eff["out"]), now=now, baseline=eff["baseline"])
    b, cur = t["breakdown"], eff["currency"]
    money = lambda v: store.format_money(v, cur)  # noqa: E731
    data = {"window": window, "label": label, "currency": cur, "saved": t["saved"], "local_tokens": t["local_tokens"],
            "cloud_tokens": t["cloud_tokens"], "breakdown": b, "version": version()}
    md = ["### Local Fleet savings receipt", "", f"Window: {label}. Plugin {version()}."]
    if t["saved"] is None:
        md += ["", f"**Avoided API cost: unavailable.** {b['baseline'].get('source')}."]
    else:
        md += ["", f"**Avoided API cost (estimated): {money(t['saved'])}**", "",
               "| | Tokens run locally (observed) | Rate per million | Value |", "|---|---|---|---|",
               f"| Input | {b['local_in']:,} | {money(b['price_in_per_m'])} | {money(b['saved_in'])} |",
               f"| Output | {b['local_out']:,} | {money(b['price_out_per_m'])} | {money(b['saved_out'])} |",
               "", f"- **Baseline:** {b['baseline'].get('model') or 'not recorded'} ({b['baseline'].get('rates')})"]
        if b["baseline"].get("note"):
            md.append(f"- **Note:** {b['baseline']['note']}")
    cov = f"{b['coverage'] * 100:.0f}%" if b.get("coverage") is not None else "n/a"
    md += [f"- **Coverage:** {b['calls_local_counted']} of {b['calls_local']} local calls reported token counts ({cov})",
           f"- **Side tasks:** {b['aux_in'] + b['aux_out']:,} of the local tokens",
           f"- **Cloud tokens in the window:** {t['cloud_tokens']:,} (not counted)",
           f"- **Not counted:** {b['excluded']}", "", f"_{b['caveat']}_"]
    hosts = hosts_of(store.fleet().nodes)
    return mask("\n".join(md) + "\n", hosts), json.loads(mask(json.dumps(data), hosts))
