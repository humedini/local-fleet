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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .constants import FLEET_FILE, KINDS, OSES, VENDORS
from .locking import locked

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

    def _reload(self) -> None:
        self.nodes = json.loads(self.path.read_text()).get("nodes", []) if self.path.exists() else []

    @contextmanager
    def _txn(self):
        """Lock, reload what is on disk, change, save: no change from another process is lost."""
        with locked(self.path.parent):
            self._reload()
            yield
            self.save()

    def add(self, *a, **kw) -> dict:
        with self._txn():
            return self._add(*a, **kw)

    def remove(self, ref: str) -> dict:
        with self._txn():
            return self._remove(ref)

    def set_enabled(self, ref: str, enabled: bool) -> dict:
        with self._txn():
            return self._set_enabled(ref, enabled)

    def update(self, ref: str, **fields) -> dict:
        with self._txn():
            return self._update(ref, **fields)

    def record_perf(self, results: dict[str, dict]) -> None:
        """Merge bench results into the boxes on disk (by id; boxes removed meanwhile stay removed)."""
        with self._txn():
            self._record_perf(results)

    def record_health(self, results: dict[str, dict]) -> None:
        """Merge probe results into the boxes on disk (by id; edits made meanwhile are kept)."""
        with self._txn():
            self._record_health(results)

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
            raise FleetError(f"no node {ref!r}; see `hermes fleet list`")
        return node

    def _add(self, name: str, url: str, kind: str = "ollama", labels=None,
            api_key_env: str | None = None, enabled: bool = True,
            capacity_gb: float | None = None, vendor: str | None = None, os_name: str | None = None,
            memory_gb: float | None = None, title: str | None = None, members=None,
            link: str | None = None) -> dict:
        name = (name or "").strip()
        if not name or len(name) > 40 or not re.match(r"^[\w.-]+$", name):
            raise FleetError("name must be 1-40 letters, digits, '.', '_' or '-'")
        if kind not in KINDS:
            raise FleetError(f"kind must be one of {', '.join(KINDS)}")
        base_url = normalize_url(url)
        if api_key_env and not _ENV_NAME.match(api_key_env):
            raise FleetError("--api-key-env takes the NAME of an environment variable, not a key")
        _check_gb(capacity_gb, "--capacity-gb")
        _check_gb(memory_gb, "--memory-gb")
        _check_platform(vendor, os_name)
        title = _check_title(title)
        member_ids = self._member_ids(members)
        link = _check_link(link)
        for n in self.nodes:
            if n["name"].lower() == name.lower():
                raise FleetError(f"a node is already called {n['name']!r}")
            if n["base_url"].lower() == base_url.lower():
                raise FleetError(f"that address is already registered as {n['name']!r}")
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
            "memory_gb": memory_gb,
            "title": title,
            "members": member_ids,
            "link": link,
            "vendor": vendor or None,
            "os": os_name or None,
            "models": [],
            "last_health": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        self.nodes.append(node)
        return node

    def _remove(self, ref: str) -> dict:
        node = self.get(ref)
        clusters = [n["name"] for n in self.nodes if node["id"] in (n.get("members") or [])]
        if clusters:
            raise FleetError(f"{node['name']} is part of {', '.join(clusters)}; remove it from the cluster first")
        self.nodes.remove(node)
        return node

    def _member_ids(self, members) -> list[str]:
        """Resolve member refs to ids: existing, distinct, single boxes (not clusters)."""
        ids = []
        for ref in members or []:
            m = self.get(ref)
            if m.get("members"):
                raise FleetError(f"{m['name']} is itself a cluster")
            if m["id"] not in ids:
                ids.append(m["id"])
        if ids and len(ids) < 2:
            raise FleetError("a cluster needs at least two members")
        return ids

    def clusters_of(self, node_id: str) -> list[dict]:
        return [n for n in self.nodes if node_id in (n.get("members") or [])]

    def _set_enabled(self, ref: str, enabled: bool) -> dict:
        node = self.get(ref)
        node["enabled"] = enabled
        node["updated_at"] = now_iso()
        return node

    def _update(self, ref: str, **fields) -> dict:
        """Change a node's vendor, os, labels, capacity_gb or memory_gb."""
        node = self.get(ref)
        _check_platform(fields.get("vendor"), fields.get("os"))
        _check_gb(fields.get("capacity_gb"), "--capacity-gb")
        _check_gb(fields.get("memory_gb"), "--memory-gb")
        for key in ("vendor", "os", "labels", "capacity_gb", "memory_gb"):
            if fields.get(key) is not None:
                node[key] = fields[key] or None
        if fields.get("title") is not None:
            node["title"] = _check_title(fields["title"])
        if fields.get("link") is not None:
            node["link"] = _check_link(fields["link"])
        if fields.get("members") is not None:
            ids = self._member_ids(fields["members"])
            if node["id"] in ids:
                raise FleetError("a cluster cannot contain itself")
            node["members"] = ids
        node["updated_at"] = now_iso()
        return node

    def _record_perf(self, results: dict[str, dict]) -> None:
        """Store each bench result (keyed by node id); keep the last good speed when a run is skipped."""
        for n in self.nodes:
            r = results.get(n["id"])
            if r is None:
                continue
            if r.get("tps"):
                n["perf"] = r
            else:
                n["perf_note"] = r

    def _record_health(self, results: dict[str, dict]) -> None:
        """Store each probe's snapshot (keyed by node id) and the models it saw."""
        for n in self.nodes:
            snap = results.get(n["id"])
            if snap is None:
                continue
            n["last_health"] = snap
            if snap.get("models"):
                n["models"] = snap["models"]
            n["updated_at"] = snap["checked_at"]


def _check_title(title):
    """A display name: 1-40 printable characters, or None to clear."""
    if title is None:
        return None
    title = " ".join(str(title).split())
    if not title:
        return None
    if len(title) > 40 or not title.isprintable():
        raise FleetError("a display name is 1-40 printable characters")
    return title


def _check_link(link):
    link = " ".join(str(link or "").split())
    if len(link) > 30:
        raise FleetError("--link is a short label such as '200 GbE'")
    return link or None


def display_name(node: dict) -> str:
    return node.get("title") or node["name"]


def _check_gb(value, flag):
    if value is not None and not 0 < value <= 4096:
        raise FleetError(f"{flag} must be between 0 and 4096")


def _check_platform(vendor, os_name):
    if vendor and vendor not in VENDORS:
        raise FleetError(f"--vendor must be one of {', '.join(VENDORS)}")
    if os_name and os_name not in OSES:
        raise FleetError(f"--os must be one of {', '.join(OSES)}")


# Name hints for boxes whose platform was not given. A guess only; `hermes fleet set` overrides.
_GUESSES = (
    (("gx10", "spark", "dgx", "gb10", "jetson", "thor", "rtx", "4090", "5090", "a100", "h100", "nvidia"), "nvidia", "linux"),
    (("mac", "mini", "studio", "mbp", "macbook", "m1", "m2", "m3", "m4", "m5"), "apple", "macos"),
    (("strix", "ryzen", "radeon", "amd", "halo", "framework"), "amd", None),
    (("arc", "intel", "nuc"), "intel", None),
)


def platform(node: dict) -> dict:
    """{"vendor", "os", "guessed"} for display: the node's own values, else a guess from its name."""
    vendor, os_name = node.get("vendor"), node.get("os")
    guessed = False
    if not vendor or not os_name:
        parts = [t for t in re.split(r"[^a-z0-9]+", node.get("name", "").lower()) if t]
        for hints, v, o in _GUESSES:
            if any(t == h or (len(h) >= 4 and t.startswith(h)) for t in parts for h in hints):
                if not vendor:
                    vendor, guessed = v, True
                if not os_name and o:
                    os_name, guessed = o, True
                break
    return {"vendor": vendor, "os": os_name, "guessed": guessed}


def public_node(node: dict) -> dict:
    """A node as shown to the agent or the Desktop: everything but how its secret is found."""
    out = {k: v for k, v in node.items() if k != "api_key_env"}
    out["needs_key"] = bool(node.get("api_key_env"))
    out["platform"] = platform(node)
    return out
