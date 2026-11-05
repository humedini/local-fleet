"""Load a model on a box before Hermes is switched to it, so the first message after a switch
(failover, failback, Use freest) does not wait for a cold load.

Ollama only: an empty `/api/generate` with `keep_alive` loads the model and returns when it is in
memory. Other kinds manage their own memory and are left alone.
"""
from __future__ import annotations

import httpx

from .health import node_headers, origin


def warm(node: dict, model: str, resident: list[str], timeout: float = 120.0, keep_alive: str | int = "30m",
         transport: httpx.BaseTransport | None = None, refresh: bool = False) -> dict:
    """{"warmed": bool, "detail": str}. Never raises. `refresh` also sends `keep_alive` to a model
    already in memory (Ollama then only resets its unload timer; nothing reloads)."""
    if node.get("kind") != "ollama" or not model:
        return {"warmed": False, "detail": "not an ollama box"}
    if model in (resident or []) and not refresh:
        return {"warmed": False, "detail": "already in memory"}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=5), transport=transport) as c:
            r = c.post(f"{origin(node['base_url'])}/api/generate", headers=node_headers(node),
                       json={"model": model, "keep_alive": keep_alive})
            r.raise_for_status()
        return {"warmed": True, "detail": f"loaded {model}"}
    except httpx.TimeoutException:
        return {"warmed": False, "detail": f"still loading after {timeout:.0f}s"}
    except httpx.HTTPStatusError as e:
        return {"warmed": False, "detail": f"Ollama refused the load (HTTP {e.response.status_code})"}
    except (httpx.HTTPError, ValueError) as e:
        return {"warmed": False, "detail": f"load failed ({type(e).__name__})"}
