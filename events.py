"""The flight recorder: what happened to routing, in order.

Recorded here (`events.jsonl`, the last KEEP events): box health changes, routing decisions that
changed Hermes's config, side-task moves, rehearsals, maintenance, pauses and drift. What Hermes
actually **served** comes from the traffic log instead (one line per real call): the timeline adds
a "served" event whenever the endpoint answering calls changes, so configured and served routes are
shown separately, including core fallback taking over within a turn.
"""
from __future__ import annotations

import json
import os
import time

from . import store

FILE = "events.jsonl"
KEEP = 400


def record(kind: str, text: str, **fields) -> None:
    """Append one event. Never raises: the recorder must not break routing. Addresses are masked
    before anything is stored (a probe error can quote a URL), so the recorder file, the Desktop and
    the JSON export never hold one, whatever the privacy setting."""
    try:
        from .render import hosts_of, mask
        hosts = hosts_of(store.fleet().nodes)
        clean = {k: mask(v, hosts) if isinstance(v, str) else v for k, v in fields.items() if v is not None}
        line = {"t": round(time.time(), 2), "kind": kind, "text": mask(text, hosts), **clean}
        with store.transaction():
            path = store.data_dir() / FILE
            with open(path, "a") as f:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")
            if path.stat().st_size > 200_000:
                lines = path.read_text().splitlines()[-KEEP:]
                tmp = path.with_suffix(".tmp")
                tmp.write_text("\n".join(lines) + "\n")
                os.replace(tmp, path)
    except Exception:
        pass


def load(limit: int = 60) -> list[dict]:
    path = store.data_dir() / FILE
    if not path.exists():
        return []
    out = []
    for raw in path.read_text().splitlines()[-KEEP:]:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out[-limit:]


def served_changes(traffic_lines: list[dict], names: dict[str, str]) -> list[dict]:
    """A "served" event each time the endpoint answering Hermes's main calls changes."""
    out, last = [], None
    for ln in traffic_lines:
        if ln.get("aux"):
            continue
        who = names.get(ln.get("n"), ln.get("n")) if ln.get("n") else f"cloud · {ln.get('p') or '?'}"
        if who != last:
            ok = "" if ln.get("ok", 1) else " (call failed)"
            out.append({"t": ln.get("t", 0), "kind": "served", "text": f"{who} · {ln.get('m') or ''}{ok}".strip(), "box": who})
            last = who
    return out


def timeline(limit: int = 40) -> list[dict]:
    """Recorded events and served changes, newest last."""
    from . import traffic
    names = {n["id"]: n.get("title") or n["name"] for n in store.fleet().nodes}
    merged = load(200) + served_changes(traffic.load(7 * 86400), names)
    merged.sort(key=lambda e: e.get("t", 0))
    return merged[-limit:]
