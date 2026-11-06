"""Fleet doctor: readiness checks with fixes. `checks()` feeds the Desktop drawer (structured) and
`run()` the terminal (text). Every check is {id, level (ok|info|warn|error), title, detail, fix}, where
fix is {"action": <Desktop backend action>, "label"} for one-click fixes or {"command": "..."} to type.
It complements `hermes doctor` (Hermes itself) and `hermes plugins doctor` (the plugin's packaging).
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import config_write, store
from .engine import active_exclusions, drift, model_tiers, private_status, probe
from .readiness import DEFAULT_MIN_CONTEXT, verdict
from .render import redact, target_text


def _check(id_, level, title, detail="", fix=None):
    return {"id": id_, "level": level, "title": title, "detail": detail, "fix": fix}


def _plugin_enabled() -> bool | None:
    try:
        from hermes_cli.config import load_config_readonly
        enabled = ((load_config_readonly() or {}).get("plugins") or {}).get("enabled") or []
        return "local-fleet" in enabled
    except Exception:
        return None


def is_private_address(url: str) -> bool:
    """LAN, loopback, tailnet (100.64/10, *.ts.net) or a LAN-style name: fine for plain HTTP."""
    import ipaddress
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith((".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host  # a bare LAN hostname
    return not ip.is_global  # LAN, loopback, link-local, CGNAT/tailnet 100.64/10, reserved ranges


def _watch_check(before: dict, applied) -> dict | None:
    """Is a watch loop keeping routing current? Judged from the loop's own heartbeat, read before
    the doctor probes: the doctor's probe (or any other) is not evidence that anything keeps running."""
    if not applied:
        return None
    at, every = before.get("watch_at"), float(before.get("watch_interval_s") or 30)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() if at else None
    if age is not None and age <= max(3 * every, 120):
        return _check("watch", "ok", f"Watch loop running (last tick {int(age)} s ago)")
    return _check("watch", "info", "Nothing is keeping routing current" if age is None else
                  f"The watch loop has not ticked for {int(age // 60)} min",
                  "Switching between boxes continuously needs the watch loop (a probe from here or the Desktop does not count).",
                  {"command": "hermes fleet watch --interval 30"})


def checks() -> list[dict]:
    before = store.load_state()  # evidence from before this doctor run's own probe
    settings, f, results = probe()
    state = store.load_state()
    out = []
    en = _plugin_enabled()
    out.append(_check("enabled", "ok" if en else "error" if en is False else "warn",
                      "Plugin enabled for this profile" if en else "Plugin not enabled for this profile",
                      "" if en else "Tools, hooks and /fleet only load for enabled plugins.",
                      None if en else {"command": "hermes plugins enable local-fleet"}))
    if not f.nodes:
        out.append(_check("boxes", "error", "No boxes registered", "Add at least one inference box.",
                          {"command": "hermes fleet add --name gx10 --url http://<host>:11434/v1 --kind ollama"}))
    excluded = active_exclusions(dict(state))
    tiers = [m for m in model_tiers(settings) if m]
    min_ctx = int(settings.get("min_context") or DEFAULT_MIN_CONTEXT)
    for n in f.enabled():
        h = results.get(n["id"]) or {}
        name = n.get("title") or n["name"]
        if n["base_url"].lower().startswith("http://") and not is_private_address(n["base_url"]):
            out.append(_check(f"http:{n['id']}", "warn", f"{name} uses plain HTTP to a public address",
                              "Prompts and replies cross the internet unencrypted. Use HTTPS, a tailnet or your LAN.",
                              {"command": f"hermes fleet rm {n['name']} && hermes fleet add --name {n['name']} --url https://…"}))
        if h.get("status") not in ("ok", "degraded"):
            out.append(_check(f"down:{n['id']}", "error", f"{name} is not answering", redact(h.get("detail") or ""),
                              {"action": "probe", "label": "Probe again"}))
            continue
        if n["id"] in excluded:
            ex = excluded[n["id"]]
            out.append(_check(f"excluded:{n['id']}", "info", f"{name}: {ex['kind']}",
                              "Left out of new selections." + (f" Until {ex['until'][11:16]} UTC." if ex.get("until") else ""),
                              {"action": f"include:{n['id']}", "label": "Put back in selection"}))
        if n.get("api_key_env"):
            from agent.secret_scope import get_secret
            if not get_secret(n["api_key_env"]):
                out.append(_check(f"key:{n['id']}", "error", f"{name} needs {n['api_key_env']}, which is not set",
                                  "Store it as a Hermes secret.", {"command": f"hermes config set {n['api_key_env']} <key>"}))
        for m in tiers:
            if m in (h.get("models") or []):
                ok, why = verdict((n.get("caps") or {}).get(m), min_ctx)
                if not ok:
                    out.append(_check(f"ready:{n['id']}:{m}", "warn", f"{name} cannot run Hermes on {m}", why))
                elif why.startswith("context not set"):
                    out.append(_check(f"ctx:{n['id']}:{m}", "warn", f"{name}: {m} has no context size set",
                                      "Ollama's default context may be smaller than Hermes's system prompt (~15k tokens). "
                                      "Create a variant with a larger num_ctx.",
                                      {"command": f"printf 'FROM {m}\\nPARAMETER num_ctx {min_ctx}\\n' > Modelfile && ollama create {m}-{min_ctx // 1024}k -f Modelfile"}))
    if tiers and not any(tiers[0] in ((results.get(n["id"]) or {}).get("models") or []) for n in f.enabled()):
        out.append(_check("main-model", "warn", f"No box has your main model {tiers[0]}", "Hermes would use a fallback model or cloud.",
                          {"command": f"hermes fleet model <a model your boxes have>   (or pull {tiers[0]} onto a box)"}))
    cp, cm = settings.get("cloud_provider"), settings.get("cloud_model")
    if not (cp and cm):
        out.append(_check("cloud", "error", "No cloud backup set", "Used when every box is down, and by prefer-cloud mode.",
                          {"command": "hermes fleet cloud <provider> <model>"}))
    elif not settings.get("private_only") and not config_write.has_fallback(config_write.fallback_chain(), cp, cm):
        out.append(_check("fallback", "warn", f"{cp}/{cm} is not on fallback_providers",
                          "Hermes would have no cloud safety net within a turn.", {"action": "reapply", "label": "Reapply"}))
    for d in drift(state):
        out.append(_check(f"drift:{d['what']}", "warn", f"Changed outside Local Fleet: {d['what']}", d["detail"],
                          {"action": "reapply", "label": "Reapply", "alt": {"action": "relinquish", "label": "Stop managing"}}))
    st = private_status()
    if st["on"]:
        out.append(_check("private", "ok" if st["in_force"] else "error",
                          "Private inference in force" if st["in_force"] else "Private inference is NOT fully in force",
                          st["scope"] if st["in_force"] else "; ".join(f"{p['what']}: {p['detail']}" for p in st["problems"]),
                          None if st["in_force"] else {"command": "hermes fleet private on   (re-applies what Local Fleet owns; "
                                                                  "fix the rest in config.yaml)"}))
    if any((b or {}).get("api_key") for b in (state.get("aux_original") or {}).values() if isinstance(b, dict)):
        out.append(_check("old-key", "warn", "Local Fleet's state holds a side-task API key from an older version",
                          "Saved when side tasks were first moved, before keys were left alone. Turning side tasks off "
                          "puts it back in config.yaml and drops it from Local Fleet's state.",
                          {"command": "hermes fleet aux off"}))
    applied = state.get("applied")
    out.append(_check("routing", "ok" if applied else "info",
                      f"Routed to {target_text(applied)}" if applied else "Routing is off: Hermes uses its own primary",
                      "" if applied else "Auto-pick box turns routing on.", None if applied else {"action": "use", "label": "Auto-pick box"}))
    w = _watch_check(before, applied)
    if w:
        out.append(w)
    return out


def run() -> tuple[bool, list[str]]:
    items = checks()
    icon = {"ok": "✓", "info": "·", "warn": "!", "error": "✗"}
    lines = ["local-fleet doctor"]
    for c in items:
        lines.append(f"  {icon[c['level']]} {redact(c['title'])}" + (f": {redact(c['detail'])}" if c["detail"] else ""))
        fix = c.get("fix") or {}
        if fix.get("command"):
            lines.append(f"      fix: {fix['command']}")
        elif fix.get("action"):
            lines.append(f"      fix: {fix.get('label')} (Desktop doctor drawer)")
    ok = not any(c["level"] == "error" for c in items)
    lines.append("  OK" if ok else "  NOT READY")
    return ok, lines
