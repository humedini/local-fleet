"""Can this box actually run Hermes on this model? Evidence per box and model, with where it came from.

Hermes needs tool calling and a context window big enough for its system prompt. For Ollama boxes
the evidence is Ollama's own `POST /api/show` (capabilities: tools, vision; `num_ctx` in the model's
parameters) and `/api/ps` (the context a loaded model is actually running with). A box is rejected
for a model only on verified evidence (Ollama says no tools, or a verified context below
`min_context`); what cannot be verified is shown as unknown, never guessed. Other kinds report no
capabilities, so they stay unknown. Results are cached per box and model for CACHE_S.
"""
from __future__ import annotations

import httpx

from .fleet import now_iso
from .health import node_headers, origin

CACHE_S = 3600
DEFAULT_MIN_CONTEXT = 32768


def _num_ctx(parameters: str) -> int | None:
    for line in (parameters or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "num_ctx":
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def inspect(client: httpx.Client, node: dict, model: str, ps_context: int | None = None) -> dict:
    """{"tools", "vision", "context", "context_source", "source", "checked_at"}; None = unknown."""
    out = {"tools": None, "vision": None, "context": None, "context_source": None, "source": None,
           "checked_at": now_iso()}
    if node.get("kind") != "ollama":
        out["source"] = f"{node.get('kind')} does not report capabilities"
        return out
    try:
        r = client.post(f"{origin(node['base_url'])}/api/show", headers=node_headers(node), json={"model": model})
        r.raise_for_status()
        d = r.json()
    except Exception as e:  # unknown, never guessed
        out["source"] = f"/api/show failed ({type(e).__name__})"
        return out
    caps = d.get("capabilities")
    if isinstance(caps, list):
        out["tools"], out["vision"] = "tools" in caps, "vision" in caps
        out["source"] = "verified: Ollama /api/show"
    ctx = _num_ctx(d.get("parameters") or "")
    if ctx:
        out["context"], out["context_source"] = ctx, "model file num_ctx"
    elif ps_context:
        out["context"], out["context_source"] = ps_context, "running context (/api/ps)"
    else:
        out["context_source"] = "server default (not set in the model)"
    return out


def verdict(caps: dict | None, min_context: int) -> tuple[bool, str]:
    """(usable, reason). Rejects only on verified evidence."""
    if not caps:
        return True, "not checked yet"
    if caps.get("tools") is False:
        return False, "no tool calling (verified)"
    ctx = caps.get("context")
    if ctx and ctx < min_context:
        return False, f"context {ctx} < {min_context} needed ({caps.get('context_source')})"
    if ctx is None and caps.get("source", "").startswith("verified"):
        return True, "context not set in the model: Ollama's default may be too small for Hermes"
    return True, "ok"


def refresh(nodes: list[dict], results: dict, models: list[str], timeout: float = 5.0,
            transport: httpx.BaseTransport | None = None) -> dict:
    """{node_id: {model: caps}} for tier models each healthy box has, re-checked when older than CACHE_S."""
    from datetime import datetime, timezone
    out = {}
    with httpx.Client(timeout=timeout, transport=transport) as client:
        for n in nodes:
            snap = results.get(n["id"]) or {}
            if snap.get("status") not in ("ok", "degraded"):
                continue
            cached = n.get("caps") or {}
            for m in models:
                if m not in (snap.get("models") or []):
                    continue
                c = cached.get(m)
                if c and c.get("checked_at"):
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(c["checked_at"])).total_seconds()
                    if age < CACHE_S and c.get("source", "").startswith("verified"):
                        continue
                out.setdefault(n["id"], {})[m] = inspect(client, n, m, (snap.get("contexts") or {}).get(m))
    return out
