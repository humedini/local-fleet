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
            return _view(engine.apply_policy())
        engine.aux_off()
        return _view()

    return await asyncio.to_thread(run)


@router.post("/use")
async def use(body: dict):
    node = str(body.get("node") or "")
    try:
        if node in ("", "freest"):
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
