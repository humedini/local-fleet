"""The only module that changes Hermes's own config: the primary model and the cloud entry on
`fallback_providers`. Same path core's `hermes fallback` takes (load_config -> change ->
save_config), so formatting and comments survive and managed installs refuse the write.

Keys (Hermes 0.22): `model.provider`, `model.default` (the model id), `model.base_url`,
`model.api_mode`, `model.key_env` (names the env var holding a key; never the key itself).
`fallback_providers` entries need `provider` and `model`.
"""
from __future__ import annotations

_MODEL_KEYS = ("provider", "default", "base_url", "api_mode", "key_env")


def _load():
    from hermes_cli.config import load_config
    return load_config()


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
    if target["kind"] == "local":
        block = {"provider": "custom", "default": target["model"], "base_url": target["base_url"],
                 "api_mode": "chat_completions"}
        if node and node.get("api_key_env"):
            block["key_env"] = node["api_key_env"]
        return block
    return {"provider": target["provider"], "default": target["model"]}


def set_primary(block: dict) -> dict:
    """Replace the routing keys of `model:` with `block`; other model keys are kept.
    Returns the block that was there before."""
    cfg = _load()
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
    cfg = _load()
    chain = list(cfg.get("fallback_providers") or [])
    if has_fallback(chain, provider, model):
        return False
    chain.append({"provider": provider, "model": model})
    cfg["fallback_providers"] = chain
    _save(cfg)
    return True


def fallback_chain() -> list:
    return list(_load().get("fallback_providers") or [])
