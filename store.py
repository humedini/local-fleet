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
    try:
        out["currency"] = currency_code(out.get("currency"))
    except ValueError:
        out["currency"] = DEFAULTS["currency"]
    return out


def set_delegation_backend(name: str) -> None:
    """Point `delegation.backend` at `name` (applies from each session's next session)."""
    if _ctx is not None and getattr(_ctx, "delegation_backends", None) is not None:
        _ctx.delegation_backends.set_global_backend(name)
        return
    from hermes_cli.config import save_config
    save_config({"delegation": {"backend": name}}, preserve_keys={("delegation", "backend")}, merge_existing=True)


def delegation_backend() -> str:
    from hermes_cli.config import load_config_readonly
    return str(((load_config_readonly() or {}).get("delegation") or {}).get("backend") or "default")


_SYMBOLS = {"£": "GBP", "€": "EUR", "$": "USD", "¥": "JPY", "₹": "INR", "₩": "KRW", "A$": "AUD", "C$": "CAD"}
CURRENCY_SIGN = {"GBP": "£", "EUR": "€", "USD": "$", "JPY": "¥", "INR": "₹", "KRW": "₩", "AUD": "A$", "CAD": "C$",
                 "CHF": "CHF ", "CNY": "CN¥", "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "NZD": "NZ$"}


_NO_MINOR_UNITS = {"JPY", "KRW", "VND", "CLP", "ISK"}


def currency_code(value) -> str:
    """'£' / 'gbp' / 'GBP' -> 'GBP'. Raises ValueError for anything that is not a 3-letter code or a known symbol."""
    v = str(value or "").strip()
    code = _SYMBOLS.get(v, v.upper())
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"{value!r} is not a currency code (ISO 4217, e.g. GBP, EUR, USD) or a known symbol")
    return code


def format_money(amount: float, code: str) -> str:
    """Terminal formatting: a known sign in front, else the code after (12.50 PLN)."""
    sign = CURRENCY_SIGN.get(code)
    digits = 0 if amount >= 100 or code in _NO_MINOR_UNITS else 2
    return f"{sign}{amount:,.{digits}f}" if sign else f"{amount:,.{digits}f} {code}"


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
