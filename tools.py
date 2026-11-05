"""Agent tool handlers. Each returns a JSON string and never raises."""
from __future__ import annotations

import json
import re

import httpx

from . import engine, store
from .fleet import public_node
from .health import node_headers, origin

_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}(:[A-Za-z0-9._-]{1,64})?$")
PULL_TIMEOUT_S = 1800


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg})


def fleet_ready() -> bool:
    try:
        return bool(store.fleet().nodes)
    except Exception:
        return False


def spark_status(args: dict, **kwargs) -> str:
    try:
        d = engine.apply_policy(dry_run=True)
        nodes = [public_node(n) for n in store.fleet().nodes]
        return json.dumps({"ok": True, "mode": d["mode"], "would_route_to": d["target"], "reason": d["reason"],
                           "freest_node_id": d["freest_node_id"], "healthy_locals": d["healthy_locals"],
                           "applied_now": store.load_state().get("applied"), "nodes": nodes})
    except Exception as e:
        return _err(f"status failed: {e}")


def spark_list_nodes(args: dict, **kwargs) -> str:
    try:
        return json.dumps({"ok": True, "nodes": [public_node(n) for n in store.fleet().nodes]})
    except Exception as e:
        return _err(f"list failed: {e}")


def spark_pull_model(args: dict, **kwargs) -> str:
    try:
        node = store.fleet().find(str(args.get("node", "")))
        model = str(args.get("model", "")).strip()
        if node is None:
            return _err("unknown node; see spark_list_nodes")
        if node.get("kind") != "ollama":
            return _err(f"{node['name']} is kind {node.get('kind')}; pulls are only for ollama nodes")
        if not _TAG.match(model):
            return _err("not an Ollama model tag")
        url = f"{origin(node['base_url'])}/api/pull"
        last = {}
        with httpx.Client(timeout=httpx.Timeout(PULL_TIMEOUT_S, connect=5)) as c:
            with c.stream("POST", url, json={"model": model, "stream": True}, headers=node_headers(node)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line.strip():
                        last = json.loads(line)
                        if last.get("error"):
                            return _err(f"ollama: {last['error']}")
        return json.dumps({"ok": last.get("status") == "success", "node": node["name"], "model": model,
                           "status": last.get("status", "unknown")})
    except httpx.TimeoutException:
        return _err(f"pull still running after {PULL_TIMEOUT_S}s; check `ollama ps` on the box")
    except Exception as e:
        return _err(f"pull failed: {e}")
