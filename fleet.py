"""The fleet registry: nodes persisted as JSON in the plugin's data directory.

Never stores secrets: a node that needs a key names the environment variable holding it
(`api_key_env`), and the key is read only when that node is probed or used.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .constants import FLEET_FILE, KINDS

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FleetError(ValueError):
    """A user-facing problem with a fleet change (bad URL, duplicate, unknown node)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    """Validate an OpenAI-compatible base URL and return it without a trailing slash."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FleetError(f"not an http(s) URL: {url!r}")
    if parts.username or parts.password:
        raise FleetError("put credentials in an env var (--api-key-env), not in the URL")
    if parts.query or parts.fragment:
        raise FleetError("base URL must not carry a query or fragment")
    return url.rstrip("/")


def write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


class Fleet:
    """Load, change and save the node list in `<data_dir>/fleet.json`."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / FLEET_FILE
        self.nodes: list[dict] = []
        if self.path.exists():
            self.nodes = json.loads(self.path.read_text()).get("nodes", [])

    def save(self) -> None:
        write_json_atomic(self.path, {"version": 1, "nodes": self.nodes})

    def enabled(self) -> list[dict]:
        return [n for n in self.nodes if n.get("enabled", True)]

    def find(self, ref: str) -> dict | None:
        """A node by id, or by name ignoring case."""
        ref = (ref or "").strip()
        for n in self.nodes:
            if n["id"] == ref or n["name"].lower() == ref.lower():
                return n
        return None

    def get(self, ref: str) -> dict:
        node = self.find(ref)
        if node is None:
            raise FleetError(f"no node {ref!r}; see `hermes spark list`")
        return node

    def add(self, name: str, url: str, kind: str = "ollama", labels=None,
            api_key_env: str | None = None, enabled: bool = True,
            capacity_gb: float | None = None) -> dict:
        name = (name or "").strip()
        if not name or len(name) > 40 or not re.match(r"^[\w.-]+$", name):
            raise FleetError("name must be 1-40 letters, digits, '.', '_' or '-'")
        if kind not in KINDS:
            raise FleetError(f"kind must be one of {', '.join(KINDS)}")
        base_url = normalize_url(url)
        if api_key_env and not _ENV_NAME.match(api_key_env):
            raise FleetError("--api-key-env takes the NAME of an environment variable, not a key")
        if capacity_gb is not None and not 0 < capacity_gb <= 4096:
            raise FleetError("--capacity-gb must be between 0 and 4096")
        for n in self.nodes:
            if n["name"].lower() == name.lower():
                raise FleetError(f"a node is already called {n['name']!r}")
            if n["base_url"].lower() == base_url.lower():
                raise FleetError(f"{base_url} is already registered as {n['name']!r}")
        stamp = now_iso()
        node = {
            "id": uuid.uuid4().hex[:6],
            "name": name,
            "base_url": base_url,
            "kind": kind,
            "labels": sorted({str(label).strip() for label in (labels or []) if str(label).strip()}),
            "enabled": enabled,
            "api_key_env": api_key_env or None,
            "capacity_gb": capacity_gb,
            "models": [],
            "last_health": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        self.nodes.append(node)
        self.save()
        return node

    def remove(self, ref: str) -> dict:
        node = self.get(ref)
        self.nodes.remove(node)
        self.save()
        return node

    def set_enabled(self, ref: str, enabled: bool) -> dict:
        node = self.get(ref)
        node["enabled"] = enabled
        node["updated_at"] = now_iso()
        self.save()
        return node

    def record_health(self, results: dict[str, dict]) -> None:
        """Store each probe's snapshot (keyed by node id) and the models it saw."""
        for n in self.nodes:
            snap = results.get(n["id"])
            if snap is None:
                continue
            n["last_health"] = snap
            if snap.get("models"):
                n["models"] = snap["models"]
            n["updated_at"] = snap["checked_at"]
        self.save()


def public_node(node: dict) -> dict:
    """A node as shown to the agent or the Desktop: everything but how its secret is found."""
    out = {k: v for k, v in node.items() if k != "api_key_env"}
    out["needs_key"] = bool(node.get("api_key_env"))
    return out
