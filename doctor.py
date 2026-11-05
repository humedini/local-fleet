"""`hermes spark doctor`: end-to-end readiness, as (ok, lines)."""
from __future__ import annotations

from pathlib import Path

from . import config_write, store
from .engine import probe
from .health import pick_freest
from .render import target_text


def run() -> tuple[bool, list[str]]:
    lines, ok = ["hermes-spark doctor"], True

    def bad(msg):
        nonlocal ok
        ok = False
        lines.append(f"  ✗ {msg}")

    settings, f, results = probe()
    lines.append(f"  nodes: {len(f.enabled())} enabled / {len(f.nodes)} total")
    if not f.nodes:
        bad("no nodes: hermes spark add --name <n> --url http://<host>:11434/v1 --kind ollama")
    want = settings.get("default_model") or ""
    for n in f.enabled():
        h = results.get(n["id"], {})
        extra = f" {h['latency_ms']}ms" if h.get("latency_ms") is not None else ""
        extra += f" load={h['load_proxy']:g}" if h.get("load_proxy") is not None else ""
        detail = "" if h.get("detail", "").startswith("ok") else f" {h.get('detail', '')}"
        has = ""
        if want and h.get("status") in ("ok", "degraded"):
            has = f"  has {want}" if want in h.get("models", []) else f"  no {want} (skipped)"
        lines.append(f"  probe {n['name']}: {h.get('status')}{extra}{detail}{has}")
        if n.get("api_key_env"):
            from agent.secret_scope import get_secret
            if not get_secret(n["api_key_env"]):
                bad(f"{n['name']} needs {n['api_key_env']}, which is not set")
        if n["base_url"].startswith("http://") and not _private(n["base_url"]):
            lines.append(f"  ! {n['name']} uses plain http to a public address; prefer https or a tailnet")
    freest = pick_freest(f.enabled(), results, want, settings.get("prefer_labels") or ())
    lines.append(f"  freest: {freest['name'] if freest else 'none'}")
    lines.append(f"  mode: {settings['mode']}")

    primary = config_write.current_primary()
    where = f" {primary['base_url']}" if primary.get("base_url") else ""
    lines.append(f"  primary: {primary.get('provider', '?')}{where} model={primary.get('default', '?')}")
    applied = store.load_state().get("applied")
    lines.append(f"  routed by spark: {target_text(applied) if applied else 'not yet (hermes spark use --freest)'}")

    cp, cm = settings.get("cloud_provider"), settings.get("cloud_model")
    chain = config_write.fallback_chain()
    if cp and cm:
        mark = "✓" if config_write.has_fallback(chain, cp, cm) else "missing (added on the next apply)"
        lines.append(f"  fallback_providers: {cp}/{cm} {mark}")
    else:
        bad("no cloud target: set one with hermes spark setup (prefer-cloud needs it, and the "
            "other modes use it when every local is down)")

    desktop = Path(__file__).parent / "desktop" / "plugin.js"
    lines.append(f"  desktop half: {'present' if desktop.exists() else 'absent'}")
    keys = [n["api_key_env"] for n in f.nodes if n.get("api_key_env")]
    lines.append(f"  secrets: {', '.join(keys) if keys else 'none required for current nodes'}")
    lines.append("  OK — ready to route" if ok and freest else
                 "  OK — no healthy local; cloud would be primary" if ok else "  NOT READY")
    return ok, lines


def _private(url: str) -> bool:
    import ipaddress
    from urllib.parse import urlsplit
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith((".local", ".lan", ".home", ".internal", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host  # bare LAN hostname
    return ip.is_private or ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")
