"""Agent tool handlers. Each returns a JSON string and never raises."""
from __future__ import annotations

import json
import re

import httpx

from . import engine, render, store
from .fleet import public_node
from .health import node_headers, origin

_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}(:[A-Za-z0-9._-]{1,64})?$")
PULL_TIMEOUT_S = 1800


def valid_tag(model: str) -> bool:
    """An Ollama library tag (`qwen3:14b`, `namespace/model:tag`). A first path segment with `.` or `:`
    names a registry host, so it is refused: a pull only ever comes from Ollama's own library."""
    if not _TAG.match(model):
        return False
    first, _, rest = model.partition("/")
    return not (rest and ("." in first or ":" in first))


def pull_approval(tool_name: str = "", args: dict | None = None, **kwargs):
    """pre_tool_call hook: every fleet_pull_model call goes to Hermes's human-approval gate first,
    because a pull can put tens of GB on a box. Other tools are not touched."""
    if tool_name != "fleet_pull_model":
        return None
    a = args if isinstance(args, dict) else {}
    model, node = str(a.get("model", "")).strip(), str(a.get("node", "")).strip()
    return {"action": "approve", "message": f"Local Fleet: pull {model or '?'} onto {node or '?'}"}


def _hide() -> bool:
    try:
        return bool(store.read_settings().get("hide_addresses"))
    except Exception:
        return True  # cannot read the setting: err on the side of hiding


def _json(v: dict) -> str:
    """With privacy on, no address reaches the agent's transcript (it may be on screen)."""
    try:
        nodes = store.fleet().nodes
    except Exception:
        nodes = []
    return json.dumps(render.scrub(v, _hide(), nodes))


def _err(msg: str) -> str:
    return _json({"ok": False, "error": msg})


def fleet_ready() -> bool:
    try:
        return bool(store.fleet().nodes)
    except Exception:
        return False


def fleet_status(args: dict, **kwargs) -> str:
    try:
        d = engine.apply_policy(dry_run=True)
        nodes = [public_node(n) for n in store.fleet().nodes]
        return _json({"ok": True, "mode": d["mode"], "would_route_to": d["target"], "reason": d["reason"],
                           "freest_node_id": d["freest_node_id"], "healthy_locals": d["healthy_locals"],
                           "applied_now": store.load_state().get("applied"), "nodes": nodes})
    except Exception as e:
        return _err(f"status failed: {e}")


def fleet_list_nodes(args: dict, **kwargs) -> str:
    try:
        return _json({"ok": True, "nodes": [public_node(n) for n in store.fleet().nodes]})
    except Exception as e:
        return _err(f"list failed: {e}")


def fleet_pull_model(args: dict, **kwargs) -> str:
    try:
        node = store.fleet().find(str(args.get("node", "")))
        model = str(args.get("model", "")).strip()
        if node is None:
            return _err("unknown node; see fleet_list_nodes")
        if node.get("kind") != "ollama":
            return _err(f"{node['name']} is kind {node.get('kind')}; pulls are only for ollama nodes")
        if not valid_tag(model):
            return _err("not an Ollama library tag (registry hosts are not allowed)")
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
        return _json({"ok": last.get("status") == "success", "node": node["name"], "model": model,
                           "status": last.get("status", "unknown")})
    except httpx.TimeoutException:
        return _err(f"pull still running after {PULL_TIMEOUT_S}s; check `ollama ps` on the box")
    except Exception as e:
        return _err(f"pull failed: {e}")
