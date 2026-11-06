"""Rehearsal packs: named, reversible simulations for demos and soak checks, built only from
rehearsals (exclusions inside Local Fleet). Nothing is stopped on any box, no process is touched
and no durable setting changes; Hermes's primary moves exactly as it would for a manual rehearsal
(only while routing is on), and warm-up and keep-loaded are skipped while a rehearsal runs.

- local-a-down     the box Hermes is on (else the least busy one) is rehearsed out
- force-cloud-hop  every enabled box is rehearsed out: cloud, or a refusal in private mode
- recover-drift    the packs' rehearsals end, routing recovers, and drift is checked and recorded

`end()` removes only the rehearsals the packs added, so a rehearsal you started yourself stays.
Every step leaves a "pack" marker in the flight recorder.
"""
from __future__ import annotations

from . import engine, events, store

PACKS = {"local-a-down": "Local A down", "force-cloud-hop": "Force cloud hop", "recover-drift": "Recover + drift"}
MINUTES = 10


def _added() -> list[str]:
    return [nid for nid, ex in (store.load_state().get("exclusions") or {}).items() if ex.get("pack")]


def _mark(name: str, text: str) -> None:
    events.record("pack", f"{PACKS[name]}: {text}", pack=name)


def run(name: str) -> dict:
    """Run one pack; returns the last routing decision plus {"pack", "note"}."""
    if name not in PACKS:
        raise ValueError(f"unknown pack {name!r}; choose from {', '.join(PACKS)}")
    _mark(name, "start (simulation: nothing is stopped on any box)")
    f = store.fleet()
    excluded = store.load_state().get("exclusions") or {}
    decision, note = None, ""
    if name == "local-a-down":
        applied = store.load_state().get("applied") or {}
        target = f.find(applied.get("node_id") or "") if applied.get("kind") == "local" else None
        if target is None:
            d = engine.apply_policy(dry_run=True)
            target = f.find(d.get("freest_node_id") or "")
        if target is None:
            note = "no box available to take out"
        elif target["id"] in excluded:
            note = f"{target.get('title') or target['name']} is already out"
        else:
            decision = engine.exclude(target["id"], "rehearsal", MINUTES, pack=name)
            note = f"{target.get('title') or target['name']} rehearsed out"
    elif name == "force-cloud-hop":
        out = [n for n in f.enabled() if n["id"] not in excluded]
        for n in out:
            decision = engine.exclude(n["id"], "rehearsal", MINUTES, pack=name)
        kind = ((decision or {}).get("target") or {}).get("kind")
        note = (f"{len(out)} box(es) rehearsed out: " + ("Hermes on cloud" if kind == "cloud" else
                "private inference refused cloud" if kind == "refused" else f"route {kind or 'unchanged'}"))
    else:
        ended = end(mark=False)
        decision = ended.get("decision")
        found = engine.drift()
        note = (f"{ended['ended']} rehearsal(s) ended; " +
                ("drift check: none, Hermes's config is as Local Fleet left it" if not found else
                 "drift check: " + "; ".join(d["detail"] for d in found)))
    _mark(name, note)
    decision = decision or engine.apply_policy(dry_run=True)
    return {**decision, "pack": name, "note": note}


def end(mark: bool = True) -> dict:
    """End every rehearsal a pack added (and only those)."""
    ids = _added()
    decision = None
    for nid in ids:
        decision = engine.include(nid)
    if mark and ids:
        events.record("pack", f"packs ended: {len(ids)} rehearsal(s) cleared")
    return {"ended": len(ids), "decision": decision}
