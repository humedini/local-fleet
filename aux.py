"""Side tasks on the fleet: point Hermes's auxiliary tasks (session titles, compression, optionally
vision) at the freest healthy box, with the cloud model as their fallback chain, while the main
conversation stays wherever the mode puts it ("cloud brain, local sidecar").

Writes `auxiliary.<task>.{provider, model, base_url, fallback_chain}` through Hermes's config
writer and remembers each task's previous block, so `hermes fleet aux off` puts them back.
Auxiliary blocks take a literal `api_key` only, never the name of an env var, so side tasks go only
to boxes that need no key: Local Fleet never writes a key into config.
Auxiliary calls are separate requests, so moving them never touches the main prompt cache.
"""
from __future__ import annotations

from . import config_write

TASKS = ("title_generation", "compression", "vision", "approval")
DEFAULT_TASKS = ("title_generation", "compression")
# Every routing and credential field of a task block. All are cleared when side tasks move, so a key
# meant for the previous endpoint never travels to a new host, and all come back on `aux off`.
_KEYS = ("provider", "model", "base_url", "fallback_chain", "api_key", "key_env", "api_key_env", "api_mode")
_PROVIDER = {"ollama": "ollama", "vllm": "vllm"}


def block(node: dict, model: str, cloud_provider: str, cloud_model: str) -> dict:
    b = {"provider": _PROVIDER.get(node.get("kind"), "custom"), "model": model, "base_url": node["base_url"]}
    if cloud_provider and cloud_model:
        b["fallback_chain"] = [{"provider": cloud_provider, "model": cloud_model}]
    return b


def current(cfg: dict, tasks) -> dict:
    aux = cfg.get("auxiliary") or {}
    return {t: {k: (aux.get(t) or {}).get(k) for k in _KEYS if (aux.get(t) or {}).get(k) not in (None, "", [])}
            for t in tasks}


def apply(tasks, blk: dict | None, saved: dict | None) -> dict:
    """Point `tasks` at `blk` (or restore `saved` when blk is None). Returns the blocks that were there."""
    cfg = config_write._load()
    before = current(cfg, tasks)
    aux = dict(cfg.get("auxiliary") or {})
    for t in tasks:
        entry = dict(aux.get(t) or {})
        for k in _KEYS:
            entry.pop(k, None)
        entry.update((saved or {}).get(t, {}) if blk is None else blk)
        aux[t] = entry
    cfg["auxiliary"] = aux
    config_write._save(cfg)
    return before
