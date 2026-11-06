"""Private inference: Hermes's model calls stay on your registered boxes, or fail.

What Local Fleet enforces when it is on, and what `status()` checks in Hermes's actual config every
time (a change made elsewhere is reported as "not in force", never assumed away):

- primary: `model` points at a registered box. With no box available Local Fleet keeps (or puts) the
  primary on a registered box anyway, so calls fail rather than reach cloud.
- `fallback_providers`: no entry outside the fleet (cloud entries are taken off and kept to put back).
- side tasks: every `auxiliary.<task>` block either follows the primary (provider auto/main/unset,
  no base_url) or points at a box, and its own `fallback_chain` is local too. Hermes core resolves an
  auto task as main provider, then the task's fallback_chain, then `fallback_providers`, and does not
  try its built-in provider discovery once a main provider is set.
- subagents: `delegation.backend` is `fleet`, whose routing refuses cloud in private mode. Other
  backends are not enforced, so Local Fleet switches to `fleet` (and back when turned off).

Not covered, and never claimed: tools that use the internet (web search, browser, MCP servers, image
generation, speech), and anything a process does outside Hermes's model routing. Not air-gapping.
"""
from __future__ import annotations

from . import config_write

FOLLOWS_PRIMARY = {"", "auto", "main"}
SCOPE = ("Covers Hermes's model calls: the primary, fallback_providers, side tasks and subagents. "
         "Tools such as web search, browser and MCP servers still use the internet; not air-gapping.")


def local_urls(nodes) -> set[str]:
    return {config_write._norm(n["base_url"]) for n in nodes if n.get("base_url")}


def _named_url(cfg: dict, provider: str) -> str:
    named = (cfg.get("providers") or {}).get(provider or "") or {}
    return named.get("api") or named.get("base_url") or ""


def is_local(block: dict, urls: set[str], cfg: dict) -> bool:
    """A provider block (primary, fallback entry, side task) whose endpoint is a registered box."""
    if not isinstance(block, dict):
        return False
    url = block.get("base_url") or _named_url(cfg, block.get("provider") or "")
    return bool(url) and config_write._norm(url) in urls


def primary_is_local(cfg: dict, urls: set[str]) -> bool:
    return is_local(config_write.current_primary(cfg), urls, cfg)


def _aux_problems(cfg: dict, urls: set[str]) -> list[str]:
    out = []
    for task, b in sorted((cfg.get("auxiliary") or {}).items()):
        if not isinstance(b, dict):
            continue  # scalar settings such as auxiliary.openrouter_model
        provider = str(b.get("provider") or "").strip().lower()
        if b.get("base_url") or provider not in FOLLOWS_PRIMARY:
            if not is_local(b, urls, cfg):
                out.append(f"auxiliary.{task} uses {b.get('provider') or 'a custom endpoint'}"
                           + (" with its own API key" if b.get("api_key") else ""))  # never the key itself
                continue
        cloud = [e for e in (b.get("fallback_chain") or []) if not is_local(e, urls, cfg)]
        if cloud:
            out.append(f"auxiliary.{task} falls back to " + ", ".join(f"{e.get('provider')}/{e.get('model')}"
                                                                  for e in cloud if isinstance(e, dict)))
    return out


def status(cfg: dict, nodes, delegation_backend: str, on: bool) -> dict:
    """{"on", "in_force", "problems": [{"what", "detail"}], "scope"}. `in_force` is True only when private
    mode is on and every covered path checks out in the config as it is now."""
    urls = local_urls(nodes)
    problems = []
    if not urls:
        problems.append({"what": "boxes", "detail": "no boxes registered"})
    if not primary_is_local(cfg, urls):
        p = config_write.current_primary(cfg)
        problems.append({"what": "primary", "detail": f"the primary is {p.get('provider') or '?'}/{p.get('default') or '?'}, not one of your boxes"})
    cloud = [e for e in (cfg.get("fallback_providers") or []) if not is_local(e, urls, cfg)]
    if cloud:
        problems.append({"what": "fallback", "detail": "fallback_providers has " + ", ".join(
            f"{e.get('provider')}/{e.get('model')}" for e in cloud if isinstance(e, dict))})
    raw = cfg.get("fallback_model")  # legacy key Hermes still appends to the chain; reported, not edited
    legacy = [e for e in ([raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else [])
              if isinstance(e, dict) and e.get("provider") and not is_local(e, urls, cfg)]
    if legacy:
        problems.append({"what": "fallback", "detail": "the legacy fallback_model key has " + ", ".join(
            f"{e.get('provider')}/{e.get('model')}" for e in legacy) + " (remove it from config.yaml)"})
    for d in _aux_problems(cfg, urls):
        problems.append({"what": "side tasks", "detail": d})
    if delegation_backend != "fleet":
        problems.append({"what": "subagents", "detail": f"delegation backend is {delegation_backend}, which Local Fleet cannot hold to your boxes"})
    return {"on": bool(on), "in_force": bool(on) and not problems, "problems": problems if on else [], "scope": SCOPE}
