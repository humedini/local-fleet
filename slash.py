"""`/fleet` in a session. Returns text; runs in the gateway process, so nothing is printed."""
from __future__ import annotations

from . import doctor, engine, store
from .constants import MODES
from .fleet import FleetError
from .render import decision_text, nodes_table, status_text

HELP = ("/fleet [status|list|stats|mode [prefer-local|prefer-cloud|auto]|use <box|best>|doctor]\n"
        "Routing changes apply from the next message.")


def handle(raw_args: str = "", **kwargs) -> str:
    from . import render
    render.HIDE["on"] = bool(store.read_settings().get("hide_addresses"))
    words = (raw_args or "").split()
    cmd, rest = (words[0].lower(), words[1:]) if words else ("status", [])
    try:
        if cmd == "status":
            active = (store.load_state().get("applied") or {}).get("node_id", "")
            return status_text(store.fleet().nodes, engine.apply_policy(dry_run=True), active)
        if cmd == "list":
            return nodes_table(store.fleet().nodes, (store.load_state().get("applied") or {}).get("node_id", ""))
        if cmd == "mode":
            if not rest:
                return f"mode: {store.read_settings()['mode']}"
            if rest[0] not in MODES:
                return f"unknown mode {rest[0]!r}; one of {', '.join(MODES)}"
            store.write_setting("mode", rest[0])
            return decision_text(engine.apply_policy(unpin=True))
        if cmd == "use" and rest:
            if rest[0].lstrip("-") in ("best", "freest"):
                return decision_text(engine.apply_policy(unpin=True))
            return decision_text(engine.apply_policy(pin=rest[0]))
        if cmd == "stats":
            from .cli import stats_text
            return stats_text()
        if cmd == "doctor":
            return "\n".join(doctor.run()[1])
    except FleetError as e:
        return f"✗ {e}"
    return HELP
