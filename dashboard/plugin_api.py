"""REST for the Desktop chip and fleet panel, mounted at /api/plugins/local-fleet/.

Hermes imports this file on its own, outside the plugin package, so it loads the package from
the directory above under a private module name. Every route runs the (blocking) engine in a
worker thread. Nothing here returns how a node's key is found.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

_PKG = "local_fleet_desktop_api"


def _package():
    if _PKG not in sys.modules:
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(_PKG, root / "__init__.py",
                                                      submodule_search_locations=[str(root)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = mod
        spec.loader.exec_module(mod)
    return sys.modules[_PKG]


_package()
from local_fleet_desktop_api import engine, render, store  # noqa: E402
from local_fleet_desktop_api.constants import MODES  # noqa: E402
from local_fleet_desktop_api.fleet import FleetError, public_node  # noqa: E402

router = APIRouter()


def _view(decision: dict | None = None) -> dict:
    snap = engine.snapshot()
    snap["nodes"] = [public_node(n) for n in store.fleet().nodes]
    if decision is not None:
        snap["decision"] = decision
    return snap


def _after(action) -> dict:
    """Run an action that returns a message, then the view: the response shows the state after it."""
    msg = action()
    return {**_view(), "decision": {"reason": msg}}


def _private(v):
    """Every response and error goes through here: with privacy on, no address field and no
    address inside any text (probe errors, reasons, the recorder) leaves the backend."""
    return render.scrub(v, bool(store.read_settings().get("hide_addresses")), store.fleet().nodes)


async def _run(fn, status_code: int = 404):
    def work():
        try:
            return _private(fn())
        except FleetError as e:
            return HTTPException(status_code=status_code, detail=_private(str(e)))
    out = await asyncio.to_thread(work)
    if isinstance(out, HTTPException):
        raise out
    return out


@router.get("/status")
async def status():
    """Stored state only (cheap; the chip polls this)."""
    return await _run(_view)


@router.post("/probe")
async def probe():
    """Probe now and say where the policy would route, without changing anything."""
    return await _run(lambda: _view(engine.apply_policy(dry_run=True)))


@router.post("/bench")
async def bench(body: dict | None = None):
    """Measure tokens/sec on every box that has a model in memory (never loads one from here)."""
    def run():
        engine.bench()
        return _view()
    return await _run(run)


@router.post("/delegate")
async def delegate(body: dict):
    on = bool(body.get("on"))

    def run():
        store.set_delegation_backend("fleet" if on else "default")
        return _view()

    return await _run(run)


@router.post("/aux")
async def aux_toggle(body: dict):
    on = bool(body.get("on"))

    def run():
        if on:
            store.write_setting("aux_tasks", list(store.read_settings().get("aux_tasks") or []) or ["title_generation", "compression"])
            return _view(engine.apply_policy(dry_run=True, aux_follow=True))
        engine.aux_off()
        return _view()

    return await _run(run)


@router.post("/private")
async def private(body: dict):
    on = bool(body.get("on"))
    return await _run(lambda: _after(lambda: engine.set_private(on)))


@router.post("/keep")
async def keep(body: dict):
    on = bool(body.get("on"))
    return await _run(lambda: _after(lambda: engine.set_keep(on)))


@router.post("/rename")
async def rename(body: dict):
    """Set or clear a box's display name (the handle used in commands never changes)."""
    def run():
        f = store.fleet()
        f.update(str(body.get("node") or ""), title=str(body.get("title") or ""))
        return _view()
    return await _run(run, status_code=400)


@router.post("/why")
async def why():
    """Probe and decide without changing anything: the decision inspector's data."""
    return await _run(lambda: _view(engine.apply_policy(dry_run=True)))


@router.post("/exclude")
async def exclude(body: dict):
    """Rehearse an outage (kind "rehearsal", minutes) or put a box in maintenance (kind "maintenance")."""
    kind = body.get("kind")
    if kind not in ("rehearsal", "maintenance"):
        raise HTTPException(status_code=400, detail="kind must be rehearsal or maintenance")
    return await _run(lambda: _view(engine.exclude(str(body.get("node") or ""), kind, float(body.get("minutes") or 10))))


@router.post("/include")
async def include(body: dict):
    return await _run(lambda: _view(engine.include(str(body.get("node") or ""))))


@router.post("/pack")
async def pack(body: dict):
    """Run a rehearsal pack ({"name": ...}) or end the packs' rehearsals ({"end": true})."""
    from local_fleet_desktop_api import packs

    def run():
        if body.get("end"):
            r = packs.end()
            return {**_view(r.get("decision")), "pack": {"ended": r["ended"]}}
        name = str(body.get("name") or "")
        if name not in packs.PACKS:
            raise FleetError(f"unknown pack {name!r}; choose from {', '.join(packs.PACKS)}")
        d = packs.run(name)
        return {**_view(d), "pack": {"name": name, "note": d["note"]}}
    return await _run(run, status_code=400)


@router.get("/incident")
async def incident(hours: float = 24):
    from local_fleet_desktop_api import reports
    return await _run(lambda: {"markdown": reports.incident_card(hours)})


@router.get("/receipt")
async def receipt(window: str = "today"):
    from local_fleet_desktop_api import reports

    def run():
        md, data = reports.savings_receipt("week" if window == "week" else "today")
        return {"markdown": md, "json": data}
    return await _run(run)


@router.post("/reapply")
async def reapply():
    return await _run(lambda: _view(engine.reapply()))


@router.post("/relinquish")
async def relinquish():
    return await _run(lambda: _after(engine.relinquish))


@router.get("/doctor")
async def doctor_checks():
    from local_fleet_desktop_api import doctor
    return await _run(lambda: {"checks": doctor.checks()})


@router.post("/use")
async def use(body: dict):
    node = str(body.get("node") or "")
    if node in ("", "best", "freest"):
        return await _run(lambda: _view(engine.apply_policy(unpin=True)))
    return await _run(lambda: _view(engine.apply_policy(pin=node)))


@router.post("/mode")
async def mode(body: dict):
    m = body.get("mode")
    if m not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")

    def run():
        store.write_setting("mode", m)
        return _view(engine.apply_policy(unpin=True))

    return await _run(run)
