"""The Desktop backend routes, through FastAPI's test client."""
import importlib.util
from pathlib import Path

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_engine import boxes, hermes  # noqa: F401  (fixture)

API = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"


@pytest.fixture
def client(hermes):  # noqa: F811
    spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_local_fleet", API)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/local-fleet")
    return TestClient(app)


@respx.mock
def test_status_probe_use_mode(client, hermes):  # noqa: F811
    boxes()
    s = client.get("/api/plugins/local-fleet/status").json()
    assert s["label"] == "off" and len(s["nodes"]) == 2 and all("api_key_env" not in n for n in s["nodes"])
    p = client.post("/api/plugins/local-fleet/probe").json()
    assert p["decision"]["target"]["node_name"] == "gx10" and not p["decision"]["applied"]
    u = client.post("/api/plugins/local-fleet/use", json={"node": "freest"}).json()
    assert u["label"] == "gx10" and hermes.cfg["model"]["base_url"] == "http://gx:11434/v1"
    m = client.post("/api/plugins/local-fleet/mode", json={"mode": "prefer-cloud"}).json()
    assert m["mode"] == "prefer-cloud" and m["label"] == "cloud"
    assert client.post("/api/plugins/local-fleet/mode", json={"mode": "x"}).status_code == 400
    assert client.post("/api/plugins/local-fleet/use", json={"node": "nope"}).status_code == 404
