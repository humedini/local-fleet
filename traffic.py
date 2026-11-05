"""What Hermes actually sent where: one line per model call, from Hermes's own observer hooks.

`post_api_request`, `api_request_error` and `post_auxiliary_call` hand every plugin the endpoint,
provider, model, token usage and duration of each call. We keep only those numbers (never the
request or response) as JSON lines in `<data dir>/traffic.jsonl`, matched to a fleet box by base
URL. That gives real-traffic speed, latency and error rate per box, which boxes are busy right
now (subagents included) and how many tokens ran locally instead of on cloud.

The hooks run on Hermes's request path, so recording is one small append: no network, no config
read, the fleet list cached by file mtime. Any process of the profile (gateway, CLI) appends; a
line under 4 KB written with O_APPEND does not interleave.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import store

FILE = "traffic.jsonl"
MAX_BYTES = 2_000_000
KEEP_LINES = 6000
MIN_TPS_TOKENS = 32  # shorter replies say more about load time and prompt size than about speed

_nodes_cache: tuple[float, dict] = (0.0, {})


def _norm(url: str) -> str:
    url = (url or "").strip().rstrip("/").lower()
    return url[:-3] if url.endswith("/v1") else url


def _node_index() -> dict:
    """{normalised base url: (node id, name)}, re-read only when fleet.json changes."""
    global _nodes_cache
    path = store.data_dir() / "fleet.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if mtime != _nodes_cache[0]:
        nodes = json.loads(path.read_text()).get("nodes", [])
        _nodes_cache = (mtime, {_norm(n["base_url"]): (n["id"], n["name"]) for n in nodes})
    return _nodes_cache[1]


def _tokens(usage) -> tuple[int, int]:
    u = usage if isinstance(usage, dict) else {}
    tin = u.get("prompt_tokens") or u.get("input_tokens") or 0
    tout = u.get("completion_tokens") or u.get("output_tokens") or 0
    return int(tin or 0), int(tout or 0)


def record(ok: bool, aux: str = "", **kw) -> None:
    """Append one call. Never raises (it runs inside Hermes's request path)."""
    try:
        node = _node_index().get(_norm(kw.get("base_url") or ""))
        tin, tout = _tokens(kw.get("usage"))
        line = {"t": round(time.time(), 2), "n": node[0] if node else None, "p": kw.get("provider") or "",
                "m": kw.get("response_model") or kw.get("model") or "", "in": tin, "out": tout,
                "d": round(float(kw.get("api_duration") or 0), 3), "ok": 1 if ok else 0}
        if aux:
            line["aux"] = aux
        if kw.get("session_id"):
            line["s"] = str(kw["session_id"])[-12:]
        path = store.data_dir() / FILE
        data = (json.dumps(line, separators=(",", ":")) + "\n").encode()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        if path.stat().st_size > MAX_BYTES:
            _trim(path)
    except Exception:
        pass


def _trim(path: Path) -> None:
    lines = path.read_text().splitlines()[-KEEP_LINES:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)


# Hook callbacks (Hermes passes keyword fields; **kwargs keeps them forward-compatible).
def on_post_api_request(**kw) -> None:
    record(True, **kw)


def on_api_request_error(**kw) -> None:
    record(False, **kw)


def on_post_auxiliary_call(**kw) -> None:
    record(not kw.get("error"), aux=str(kw.get("aux_task") or "aux"), **kw)


def load(since_s: float = 7 * 86400) -> list[dict]:
    path = store.data_dir() / FILE
    if not path.exists():
        return []
    cutoff = time.time() - since_s
    out = []
    for raw in path.read_text().splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if line.get("t", 0) >= cutoff:
            out.append(line)
    return out


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def summarize(lines: list[dict], prices: tuple[float, float] = (0.0, 0.0), now: float | None = None) -> dict:
    """Per-box and fleet totals over `lines` (one week by default).

    Per box: calls, errors, tokens, `live` (calls in the last 90 s), effective tok/s (median of
    the last 20 successful calls with output; includes prompt processing and queueing, so it is
    lower than a bench's decode speed) and median latency. Fleet: local vs cloud tokens and what
    the local tokens would have cost at the given per-million prices (input, output).
    """
    now = now or time.time()
    boxes: dict[str, dict] = {}
    local_in = local_out = cloud_in = cloud_out = 0
    for ln in lines:
        nid = ln.get("n")
        if nid:
            b = boxes.setdefault(nid, {"calls": 0, "errors": 0, "in": 0, "out": 0, "live": 0, "_tps": [], "_lat": []})
            b["calls"] += 1
            b["errors"] += 0 if ln.get("ok") else 1
            b["in"] += ln.get("in", 0)
            b["out"] += ln.get("out", 0)
            if now - ln.get("t", 0) <= 90:
                b["live"] += 1
            if ln.get("ok") and ln.get("out", 0) >= MIN_TPS_TOKENS and ln.get("d"):
                b["_tps"].append(ln["out"] / ln["d"])
                b["_lat"].append(ln["d"])
            local_in += ln.get("in", 0)
            local_out += ln.get("out", 0)
        else:
            cloud_in += ln.get("in", 0)
            cloud_out += ln.get("out", 0)
    for b in boxes.values():
        tps, lat = b.pop("_tps")[-20:], b.pop("_lat")[-20:]
        b["tps"] = round(_median(tps), 1) if tps else None
        b["latency_s"] = round(_median(lat), 2) if lat else None
    price_in, price_out = prices
    saved = (local_in * price_in + local_out * price_out) / 1e6 if (price_in or price_out) else None
    total = local_in + local_out + cloud_in + cloud_out
    return {"boxes": boxes, "local_tokens": local_in + local_out, "cloud_tokens": cloud_in + cloud_out,
            "local_share": round((local_in + local_out) / total, 3) if total else None,
            "saved": round(saved, 2) if saved is not None else None, "calls": len(lines)}
