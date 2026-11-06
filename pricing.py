"""The savings baseline without typing prices: the cloud backup's rates from Hermes's own rate card
(`agent.usage_pricing`, the one behind Hermes's cost display: official price snapshots, the
OpenRouter models API, models.dev). Rates are per million tokens in USD.

A subscription route (openai-codex) has no per-token price, so it is looked up as the same model on
the provider's API and said so: what the tokens would have cost on the API, not what the subscription
costs. Prices set with `hermes fleet price` always win. Looked up at most once a day (in the probe
path, never on the Desktop's polling), and only Hermes's own lookups touch the network.
"""
from __future__ import annotations

from datetime import datetime, timezone

REFRESH_S = 86400
_API_EQUIVALENT = {"openai-codex": "openai"}  # subscription route -> the pay-per-token API


def lookup(provider: str, model: str) -> dict | None:
    """{"in", "out", "currency", "model", "source", "url", "note"} or None when Hermes knows no price."""
    try:
        from agent.usage_pricing import get_pricing_entry
    except ImportError:
        return None
    note = ""
    for p in (provider, _API_EQUIVALENT.get(provider)):
        if not p:
            continue
        try:
            e = get_pricing_entry(model, p)
        except Exception:
            e = None
        if e is not None and e.input_cost_per_million and e.output_cost_per_million:
            if p != provider:
                note = (f"{provider} is a subscription; these are {p}'s API list prices for the same model, "
                        "what the tokens would have cost there")
            return {"in": float(e.input_cost_per_million), "out": float(e.output_cost_per_million), "currency": "USD",
                    "model": f"{p}/{model}", "source": f"Hermes rate card ({e.pricing_version or e.source})",
                    "url": e.source_url, "note": note,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return None


def due(cached: dict | None, provider: str, model: str) -> bool:
    if not cached or cached.get("for") != f"{provider}/{model}":
        return True
    at = cached.get("at")
    return not at or (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() > REFRESH_S


def effective(settings: dict, cached: dict | None) -> dict:
    """The rates the savings figure uses: yours if set, else the looked-up ones, else none.
    {"in", "out", "currency", "baseline": {"model", "rates", "source", "url", "note"}}"""
    pin, pout = float(settings.get("price_in_per_m") or 0), float(settings.get("price_out_per_m") or 0)
    if pin or pout:
        model = settings.get("price_model") or ""
        return {"in": pin, "out": pout, "currency": settings.get("currency") or "USD",
                "baseline": {"model": model or None, "rates": "entered by you (hermes fleet price)",
                             "source": "recorded with the prices" if model else
                                       "not recorded: re-enter the prices with --model provider/model"}}
    want = f"{settings.get('cloud_provider')}/{settings.get('cloud_model')}"
    hit = (cached or {}).get("price") if (cached or {}).get("for") == want else None
    if hit:
        return {"in": hit["in"], "out": hit["out"], "currency": hit["currency"],
                "baseline": {"model": hit["model"], "rates": f"looked up: {hit['source']}", "source": "your cloud backup",
                             "url": hit.get("url"), "note": hit.get("note") or ""}}
    return {"in": 0.0, "out": 0.0, "currency": settings.get("currency") or "USD",
            "baseline": {"model": None, "rates": "none", "source": f"no price for {want} in Hermes's rate card; "
                                                                   "set one with hermes fleet price <in> <out>"}}
