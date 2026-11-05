"""Where local-fleet keeps things, and how it reads and writes its settings.

- Fleet (`fleet.json`) and runtime state (`state.json`: what was applied, the last decision,
  the user's original primary) live in `plugin_data_dir("local-fleet")`, which survives
  `hermes plugins update`/`remove` and follows the active profile. Resolved on every call,
  never cached, so a multiplexed process lands in the right profile.
- Settings (mode, cloud target, timeouts) live in `plugins.entries.local-fleet.settings` of
  the user's config, written through the plugin context when we have one (the agent process),
  else through the same partial merge-save core uses for plugin settings (the Desktop backend).
"""
from __future__ import annotations

import json
from pathlib import Path

from .constants import DEFAULTS, MODES, PLUGIN, STATE_FILE
from .fleet import Fleet, write_json_atomic

_ctx = None  # the PluginContext from register(); None in the Desktop backend and in tests


def bind(ctx) -> None:
    global _ctx
    _ctx = ctx


def data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir(PLUGIN)


def fleet() -> Fleet:
    return Fleet(data_dir())


def load_state() -> dict:
    p = data_dir() / STATE_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(state: dict) -> None:
    write_json_atomic(data_dir() / STATE_FILE, state)


def update_state(**changes) -> dict:
    state = load_state()
    state.update(changes)
    save_state(state)
    return state


def read_settings() -> dict:
    """Defaults overlaid with the user's saved settings."""
    from hermes_cli.config import load_config_readonly
    cfg = load_config_readonly() or {}
    saved = (((cfg.get("plugins") or {}).get("entries") or {}).get(PLUGIN) or {}).get("settings") or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in saved.items() if v is not None})
    if out.get("mode") not in MODES:
        out["mode"] = DEFAULTS["mode"]
    return out


def write_setting(key: str, value) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    if _ctx is not None:
        _ctx.set_config(key, value)
        return
    from hermes_cli.config import save_config
    partial = {"plugins": {"entries": {PLUGIN: {"settings": {key: value}}}}}
    save_config(partial, preserve_keys={("plugins", "entries", PLUGIN, "settings", key)},
                merge_existing=True)
