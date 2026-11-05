"""Health probes and freest-box scoring.

Every kind answers the OpenAI `GET {base}/models`; that call decides up or down and gives
the latency. Kinds with a load signal add it:

  ollama  `GET {origin}/api/ps`: resident models and their memory. Models other than the
          one we want count as load (0.25 each, or memory / capacity when the node's
          `capacity_gb` is set), so a box already holding the wanted model looks freer.
  vllm    `GET {origin}/metrics` (Prometheus): KV-cache usage (`vllm:kv_cache_usage_perc`, or the
          older `vllm:gpu_cache_usage_perc`), else running requests (0.25 each), plus 0.25 per
          queued request.
  litellm, openai-compatible  latency only; a LiteLLM node is one gateway and balances itself.

A node whose models answer but whose load endpoint fails is `degraded`, still routable.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from .constants import PROBE_CONCURRENCY
from .fleet import now_iso

_METRIC = re.compile(r"^(vllm:[a-z_]+)(?:\{[^}]*\})?\s+([0-9.eE+-]+)$", re.M)


def origin(base_url: str) -> str:
    """`http://host:11434/v1` -> `http://host:11434` (where Ollama and vLLM keep their own APIs)."""
    p = urlsplit(base_url)
    path = p.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return f"{p.scheme}://{p.netloc}{path}"


def _secret(name: str) -> str:
    try:
        from agent.secret_scope import get_secret
    except ImportError:  # outside Hermes (unit tests): the process environment
        return os.environ.get(name, "")
    return get_secret(name) or ""


def node_headers(node: dict) -> dict:
    """Auth for one node, from the env var it names, sent to that node only."""
    env = node.get("api_key_env")
    key = _secret(env) if env else ""
    return {"Authorization": f"Bearer {key}"} if key else {}


def _snapshot(status, latency_ms, detail, models=(), load=None, free=None, resident=()):
    return {
        "checked_at": now_iso(),
        "status": status,
        "latency_ms": latency_ms,
        "free_vram_approx": free,
        "load_proxy": None if load is None else round(min(1.0, max(0.0, load)), 3),
        "detail": detail,
        "models": list(models),
        "resident": list(resident),
    }


def _ollama_load(client, node, want):
    r = client.get(f"{origin(node['base_url'])}/api/ps", headers=node_headers(node))
    r.raise_for_status()
    loaded = r.json().get("models") or []
    resident = [m.get("name") or m.get("model") for m in loaded]
    expires = {m.get("name") or m.get("model"): m.get("expires_at") for m in loaded if m.get("expires_at")}
    wanted = {want} if isinstance(want, str) else set(want or [])
    # Embedding models are small and stay loaded for search tools; they are not real load.
    others = [m for m in loaded if (m.get("name") or m.get("model")) not in wanted
              and "embed" not in (m.get("name") or m.get("model") or "").lower()]
    cap = float(node.get("capacity_gb") or 0) * 1e9
    used = sum(int(m.get("size_vram") or m.get("size") or 0) for m in loaded)
    if cap:
        load = sum(int(m.get("size_vram") or m.get("size") or 0) for m in others) / cap
        free = max(0, int(cap - used))
    else:
        load, free = 0.25 * len(others), None
    return load, free, resident, expires


def _vllm_load(client, node, want):
    r = client.get(f"{origin(node['base_url'])}/metrics", headers=node_headers(node))
    r.raise_for_status()
    metrics = {}
    for name, value in _METRIC.findall(r.text):
        metrics[name] = metrics.get(name, 0.0) + float(value)
    queued = 0.25 * metrics.get("vllm:num_requests_waiting", 0.0)
    for cache in ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"):  # renamed in newer vLLM
        if cache in metrics:
            return metrics[cache] + queued, None, [], {}
    if "vllm:num_requests_running" in metrics:
        return 0.25 * metrics["vllm:num_requests_running"] + queued, None, [], {}
    raise ValueError("no vllm load metrics")


_LOAD = {"ollama": _ollama_load, "vllm": _vllm_load}


def _detail(models: list[str], want) -> str:
    """'ok', or which tier the box serves when it lacks the main model. `want` is a model or a
    list of models in preference order."""
    tiers = [w for w in ([want] if isinstance(want, str) else list(want or [])) if w]
    if not tiers or tiers[0] in models:
        return "ok"
    fallback = next((m for m in tiers[1:] if m in models), None)
    return f"ok · fallback {fallback}" if fallback else f"ok, but no {' or '.join(tiers)}"


def probe_node(node: dict, client: httpx.Client, want="") -> dict:
    """Probe one node. Never raises: failures become a `down` snapshot with the reason."""
    t0 = time.monotonic()
    try:
        r = client.get(f"{node['base_url']}/models", headers=node_headers(node))
        r.raise_for_status()
        models = [m["id"] for m in r.json().get("data", []) if m.get("id")]
    except httpx.TimeoutException:
        return _snapshot("down", None, "timeout")
    except httpx.HTTPStatusError as e:
        return _snapshot("down", None, f"HTTP {e.response.status_code} from /models")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return _snapshot("down", None, f"{type(e).__name__}: {e}"[:120])
    latency = round((time.monotonic() - t0) * 1000)
    detail = _detail(models, want)
    loader = _LOAD.get(node.get("kind"))
    if loader is None:
        return _snapshot("ok", latency, detail, models)
    try:
        load, free, resident, expires = loader(client, node, want)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return _snapshot("degraded", latency, f"load unknown ({type(e).__name__})", models)
    snap = _snapshot("ok", latency, detail, models, load, free, resident)
    snap["expires"] = expires
    return snap


def probe_all(nodes: list[dict], timeout: float = 2.0, want="",
              transport: httpx.BaseTransport | None = None) -> dict[str, dict]:
    """Probe nodes in parallel; returns {node_id: snapshot}."""
    if not nodes:
        return {}
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as client:
        with ThreadPoolExecutor(max_workers=min(PROBE_CONCURRENCY, len(nodes))) as pool:
            futures = {n["id"]: pool.submit(probe_node, n, client, want) for n in nodes}
            return {nid: f.result() for nid, f in futures.items()}


def routable(node: dict, snap: dict | None, want: str = "") -> bool:
    """Healthy enough to take traffic, and serves the wanted model when one is set."""
    if not snap or snap["status"] not in ("ok", "degraded"):
        return False
    return not want or want in snap.get("models", [])


def score(node: dict, snap: dict, prefer_labels=(), want: str = "") -> tuple:
    """Lower is freer. Down nodes sort last; preferred labels, then faster boxes, win ties on
    load. Speed counts only when it was benched on the model being routed (speeds of different
    models are not comparable)."""
    load = snap.get("load_proxy")
    perf = node.get("perf") or {}
    tps = perf.get("tps") if want and perf.get("model") == want else None
    free = snap.get("free_vram_approx")
    lat = snap.get("latency_ms")
    affinity = 0 if set(prefer_labels) & set(node.get("labels", [])) else 1
    return (
        0 if snap["status"] in ("ok", "degraded") else 1e9,
        0.5 if load is None else load,
        affinity if prefer_labels else 0,
        -tps if tps else 0,
        0 if free is None else -free,
        9999 if lat is None else lat,
        node["name"].lower(),
    )


def pick_freest(nodes: list[dict], results: dict[str, dict], want: str = "",
                prefer_labels=()) -> dict | None:
    candidates = [n for n in nodes if routable(n, results.get(n["id"]), want)]
    if not candidates:
        return None
    return min(candidates, key=lambda n: score(n, results[n["id"]], prefer_labels, want))
