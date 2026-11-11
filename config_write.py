"""The only module that changes Hermes's own config: the primary model and the cloud entry on
`fallback_providers`. Same path core's `hermes fallback` takes (load_config -> change ->
save_config), so formatting and comments survive and managed installs refuse the write.

Keys (Hermes 0.22): `model.provider`, `model.default` (the model id), `model.base_url`,
`model.api_mode`, `model.key_env` (names the env var holding a key; never the key itself).
`fallback_providers` entries need `provider` and `model`.
"""
from __future__ import annotations

import re

# The routing keys of `model:`. Saved before the first change and put back by restore. `api_key_env`
# is a credential pointer like `key_env`: left in place it would send another vendor's key to a box.
_MODEL_KEYS = ("provider", "default", "base_url", "api_mode", "key_env", "api_key_env")
# Inline credentials on `model:` (`api` is an alias of `api_key`). Hermes ranks an inline key ahead of
# key_env, so a primary holding one is never routed: the key would follow it to another host.
INLINE_CREDENTIALS = ("api_key", "api", "key_cmd")
# Fields of a provider entry that hold a secret or produce one. Never copied into plugin data unless
# they are `${VAR}` references.
_SECRET_FIELDS = ("api_key", "api", "key_cmd", "token", "access_token", "api_token", "password", "secret")
_ENV_REF = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


class InlineKeyError(RuntimeError):
    """The primary holds an inline API key, so Local Fleet will not move it."""


def _load():
    from hermes_cli.config import load_config
    return load_config()


def raw_config() -> dict:
    """config.yaml as written, with `${VAR}` references unexpanded. Anything Local Fleet keeps in its
    own data comes from here, so an env reference stays a reference and never becomes a literal key."""
    from hermes_cli.config import read_raw_config
    return read_raw_config() or {}


def secret_fields(obj, literal_only: bool = True, _path: str = "") -> list[str]:
    """Paths of secret-bearing fields in a config block (names only, never values). With
    literal_only, `${VAR}` references do not count."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{_path}.{k}" if _path else str(k)
            if k in _SECRET_FIELDS and v not in (None, ""):
                if not (literal_only and isinstance(v, str) and _ENV_REF.match(v.strip())):
                    out.append(path)
            elif isinstance(v, (dict, list)):
                out += secret_fields(v, literal_only, path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += secret_fields(v, literal_only, f"{_path}[{i}]")
    return out


def inline_credentials(cfg: dict | None = None) -> list[str]:
    """Names of the inline credentials on `model:` (any value, `${VAR}` included). Never the values."""
    cfg = _load() if cfg is None else cfg
    model = cfg.get("model")
    return [k for k in INLINE_CREDENTIALS if isinstance(model, dict) and model.get(k) not in (None, "")]


def inline_key_message(fields: list[str]) -> str:
    names = ", ".join(f"model.{k}" for k in fields)
    return (f"Hermes's primary holds an inline API key ({names}), so Local Fleet leaves it alone: routing would "
            "send that key to another host. Put the key in ~/.hermes/.env, name it with model.key_env, "
            "and remove it from model:")


def _save(cfg: dict) -> None:
    from hermes_cli.config import save_config
    save_config(cfg)


def current_primary(cfg: dict | None = None) -> dict:
    cfg = _load() if cfg is None else cfg
    model = cfg.get("model")
    if isinstance(model, str):
        return {"default": model} if model else {}
    return {k: model[k] for k in _MODEL_KEYS if isinstance(model, dict) and model.get(k)}


def model_block(target: dict, node: dict | None = None) -> dict:
    """The `model:` keys a decision target stands for."""
    if target["kind"] in ("local", "refused"):  # refused: held on a box so calls fail, never cloud
        block = {"provider": "custom", "default": target["model"], "base_url": target["base_url"],
                 "api_mode": "chat_completions"}
        if node and node.get("api_key_env"):
            block["key_env"] = node["api_key_env"]
        return block
    return {"provider": target["provider"], "default": target["model"]}


def set_primary(block: dict, allow_inline_key: bool = False) -> dict:
    """Replace the routing keys of `model:` with `block`; other model keys are kept.
    Returns the block that was there before. Raises InlineKeyError when `model:` holds an inline
    key (restore passes allow_inline_key: it puts back the user's own primary)."""
    cfg = _load()
    held = inline_credentials(cfg)
    if held and not allow_inline_key:
        raise InlineKeyError(inline_key_message(held))
    before = current_primary(cfg)
    model = cfg.get("model")
    model = dict(model) if isinstance(model, dict) else {}
    for k in _MODEL_KEYS:
        model.pop(k, None)
    model.pop("model", None)  # legacy alias of `default`
    model.update({k: v for k, v in block.items() if v})
    cfg["model"] = model
    _save(cfg)
    return before


def has_fallback(chain: list, provider: str, model: str) -> bool:
    return any(isinstance(e, dict) and e.get("provider") == provider and e.get("model") == model
               for e in chain or [])


def ensure_fallback(provider: str, model: str) -> bool:
    """Make sure `{provider, model}` is on core's fallback chain. True if it was added."""
    if not provider or not model:
        return False
    paired = _paired_chain()
    cfg, chain = (paired[0], paired[2]) if paired else (_load(), None)
    chain = list(cfg.get("fallback_providers") or []) if chain is None else chain
    if has_fallback(chain, provider, model):
        return False
    chain.append({"provider": provider, "model": model})
    cfg["fallback_providers"] = chain
    _save(cfg)
    return True


def _norm(url: str) -> str:
    u = (url or "").strip().rstrip("/").lower()
    return u[:-3] if u.endswith("/v1") else u


def is_local_entry(entry: dict, local_urls: set[str], cfg: dict | None = None) -> bool:
    """A fallback entry is local when its endpoint is one of the registered boxes: its own base_url,
    or the URL of the named provider it refers to (`providers.<name>.api` / `base_url`)."""
    if not isinstance(entry, dict):
        return False
    url = entry.get("base_url")
    if not url:
        named = ((cfg or {}).get("providers") or {}).get(entry.get("provider") or "") or {}
        url = named.get("api") or named.get("base_url") or ""
    return bool(url) and _norm(url) in local_urls


def _paired_chain() -> tuple[dict, list, list] | None:
    """(config, expanded chain, raw chain). The raw entries keep `${VAR}` references; the expanded ones
    resolve URLs for the local/cloud decision. None when the two do not line up (Local Fleet then
    changes nothing rather than guess which raw entry is which)."""
    cfg = _load()
    chain = list(cfg.get("fallback_providers") or [])
    raw = list(raw_config().get("fallback_providers") or [])
    if len(raw) != len(chain):
        return None
    return cfg, chain, raw


def remove_non_local_fallbacks(local_urls: set[str]) -> tuple[list, list]:
    """Take the non-local entries off fallback_providers. Returns (removed, left): `removed` is what came
    off, in config.yaml form (`${VAR}` references kept), for restore; `left` names the cloud entries left
    in place because they hold a literal secret, which Local Fleet never copies into its own data."""
    paired = _paired_chain()
    if paired is None:
        return [], ["fallback_providers (config.yaml and the loaded config differ; edit it by hand)"]
    cfg, chain, raw = paired
    keep, removed, left = [], [], []
    for e, r in zip(chain, raw):
        if is_local_entry(e, local_urls, cfg):
            keep.append(r)
        elif secret_fields(r):
            keep.append(r)
            left.append(f"{r.get('provider')}/{r.get('model')}" if isinstance(r, dict) else "an entry")
        else:
            removed.append(r)
    if removed:
        cfg["fallback_providers"] = keep
        _save(cfg)
    return removed, left


def restore_fallbacks(entries: list) -> list:
    """Put entries back at the end of fallback_providers (skipping any already there), keeping the rest
    of the chain in config.yaml form. Returns what was put back."""
    if not entries:
        return []
    paired = _paired_chain()
    if paired is None:
        cfg = _load()
        chain = list(cfg.get("fallback_providers") or [])
    else:
        cfg, _, chain = paired
    back = [e for e in entries if e not in chain]
    cfg["fallback_providers"] = chain + back
    _save(cfg)
    return back


def fallback_chain() -> list:
    return list(_load().get("fallback_providers") or [])
