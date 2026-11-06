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
from local_fleet_desktop_api import engine, store  # noqa: E402
from local_fleet_desktop_api.constants import MODES  # noqa: E402
from local_fleet_desktop_api.fleet import FleetError, public_node  # noqa: E402

router = APIRouter()


def _view(decision: dict | None = None) -> dict:
    snap = engine.snapshot()
    snap["nodes"] = [public_node(n) for n in store.fleet().nodes]
    if decision is not None:
        snap["decision"] = decision
    return snap


@router.get("/status")
async def status():
    """Stored state only (cheap; the chip polls this)."""
    return await asyncio.to_thread(_view)


@router.post("/probe")
async def probe():
    """Probe now and say where the policy would route, without changing anything."""
    return await asyncio.to_thread(lambda: _view(engine.apply_policy(dry_run=True)))


@router.post("/bench")
async def bench(body: dict | None = None):
    """Measure tokens/sec on every box that has a model in memory (never loads one from here)."""
    def run():
        engine.bench()
        return _view()
    return await asyncio.to_thread(run)


@router.post("/delegate")
async def delegate(body: dict):
    on = bool(body.get("on"))

    def run():
        store.set_delegation_backend("fleet" if on else "default")
        return _view()

    return await asyncio.to_thread(run)


@router.post("/aux")
async def aux_toggle(body: dict):
    on = bool(body.get("on"))

    def run():
        if on:
            store.write_setting("aux_tasks", list(store.read_settings().get("aux_tasks") or []) or ["title_generation", "compression"])
            return _view(engine.apply_policy(dry_run=True, aux_follow=True))
        engine.aux_off()
        return _view()

    return await asyncio.to_thread(run)


@router.post("/keep")
async def keep(body: dict):
    on = bool(body.get("on"))
    return await asyncio.to_thread(lambda: {**_view(), "decision": {"reason": engine.set_keep(on)}})


@router.post("/rename")
async def rename(body: dict):
    """Set or clear a box's display name (the handle used in commands never changes)."""
    def run():
        f = store.fleet()
        f.update(str(body.get("node") or ""), title=str(body.get("title") or ""))
        return _view()
    try:
        return await asyncio.to_thread(run)
    except FleetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/why")
async def why():
    """Probe and decide without changing anything: the decision inspector's data."""
    return await asyncio.to_thread(lambda: _view(engine.apply_policy(dry_run=True)))


@router.post("/exclude")
async def exclude(body: dict):
    """Rehearse an outage (kind "rehearsal", minutes) or put a box in maintenance (kind "maintenance")."""
    kind = body.get("kind")
    if kind not in ("rehearsal", "maintenance"):
        raise HTTPException(status_code=400, detail="kind must be rehearsal or maintenance")
    try:
        return await asyncio.to_thread(lambda: _view(engine.exclude(str(body.get("node") or ""), kind, float(body.get("minutes") or 10))))
    except FleetError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/include")
async def include(body: dict):
    try:
        return await asyncio.to_thread(lambda: _view(engine.include(str(body.get("node") or ""))))
    except FleetError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reapply")
async def reapply():
    return await asyncio.to_thread(lambda: _view(engine.reapply()))


@router.post("/relinquish")
async def relinquish():
    return await asyncio.to_thread(lambda: {**_view(), "decision": {"reason": engine.relinquish()}})


@router.get("/doctor")
async def doctor_checks():
    from local_fleet_desktop_api import doctor
    return await asyncio.to_thread(lambda: {"checks": doctor.checks()})


@router.post("/use")
async def use(body: dict):
    node = str(body.get("node") or "")
    try:
        if node in ("", "best", "freest"):
            return await asyncio.to_thread(lambda: _view(engine.apply_policy(unpin=True)))
        return await asyncio.to_thread(lambda: _view(engine.apply_policy(pin=node)))
    except FleetError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/mode")
async def mode(body: dict):
    m = body.get("mode")
    if m not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")

    def run():
        store.write_setting("mode", m)
        return _view(engine.apply_policy(unpin=True))

    return await asyncio.to_thread(run)
