"""Generation speed (tokens/sec) per box, from a short real generation.

Not part of the health probe: a probe must stay cheap, while a generation occupies the box for a
second or two and, on a model that is not in memory, would load tens of GB. So a bench only runs
against a model the box already holds (the configured local model, else one in memory), unless
asked to load one, and skips boxes that look busy.

  ollama  POST /api/generate, stream off: Ollama's own eval_count / eval_duration (exact),
          plus prompt-processing speed and load time.
  others  POST /chat/completions, streamed: completion tokens (from usage when the server sends
          it, else one per content chunk) over the time from first to last token.
"""
from __future__ import annotations

import json
import time

import httpx

from .fleet import now_iso
from .health import node_headers, origin

PROMPT = "Count from 1 to 60, separated by single spaces. Output only the numbers."
MAX_TOKENS = 64
BUSY = 0.5  # load_proxy above which a box is left alone


def pick_model(node: dict, snap: dict, want: str, load: bool) -> tuple[str, str]:
    """(model, reason-if-none)."""
    models = snap.get("models") or []
    resident = snap.get("resident") or []
    if want and want in models and (want in resident or load or node.get("kind") != "ollama"):
        return want, ""
    if node.get("kind") == "ollama":
        chat = [m for m in resident if "embed" not in m.lower()]
        if chat:
            return chat[0], ""
        return "", "no model in memory (bench --load to load one)"
    usable = [m for m in models if "embed" not in m.lower()]
    return (usable[0], "") if usable else ("", "no models")


def _ollama(client, node, model):
    r = client.post(f"{origin(node['base_url'])}/api/generate", headers=node_headers(node), json={
        "model": model, "prompt": PROMPT, "stream": False,
        "options": {"num_predict": MAX_TOKENS, "temperature": 0}})
    r.raise_for_status()
    d = r.json()
    ev, evd = d.get("eval_count") or 0, d.get("eval_duration") or 0
    pc, pcd = d.get("prompt_eval_count") or 0, d.get("prompt_eval_duration") or 0
    if not ev or not evd:
        raise ValueError("no eval timings in the reply")
    return {"tps": round(ev / (evd / 1e9), 1), "tokens": ev,
            "prompt_tps": round(pc / (pcd / 1e9), 1) if pc and pcd else None,
            "load_ms": round((d.get("load_duration") or 0) / 1e6)}


def _openai(client, node, model):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": MAX_TOKENS,
            "temperature": 0, "stream": True, "stream_options": {"include_usage": True}}
    t0 = time.monotonic()
    first = last = None
    chunks = 0
    usage = None
    with client.stream("POST", f"{node['base_url']}/chat/completions", headers=node_headers(node), json=body) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            d = json.loads(line[5:])
            if d.get("usage"):
                usage = d["usage"]
            delta = ((d.get("choices") or [{}])[0].get("delta") or {})
            if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                now = time.monotonic()
                first = first or now
                last = now
                chunks += 1
    if first is None or last is None or last <= first:
        raise ValueError("too few tokens streamed to time")
    tokens = (usage or {}).get("completion_tokens") or chunks
    return {"tps": round((tokens - 1) / (last - first), 1), "tokens": tokens, "prompt_tps": None,
            "ttft_ms": round((first - t0) * 1000)}


def bench_node(node: dict, snap: dict, want: str = "", load: bool = False, timeout: float = 120.0,
               transport: httpx.BaseTransport | None = None) -> dict:
    """One box's speed. Never raises: problems come back as {"skipped": reason} or {"error": ...}."""
    if not snap or snap.get("status") not in ("ok", "degraded"):
        return {"skipped": "not healthy", "at": now_iso()}
    if not load and (snap.get("load_proxy") or 0) > BUSY:
        return {"skipped": "busy", "at": now_iso()}
    model, why = pick_model(node, snap, want, load)
    if not model:
        return {"skipped": why, "at": now_iso()}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=5), transport=transport) as client:
            out = (_ollama if node.get("kind") == "ollama" else _openai)(client, node, model)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return {"error": f"{type(e).__name__}: {e}"[:160], "model": model, "at": now_iso()}
    return {**out, "model": model, "at": now_iso()}
