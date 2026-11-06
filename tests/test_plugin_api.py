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


@respx.mock
def test_operations_routes(client, hermes):  # noqa: F811
    boxes()
    base = "/api/plugins/local-fleet"
    w = client.post(f"{base}/why").json()
    assert w["decision"]["candidates"] and w["decision"]["target"]["node_name"] == "gx10"
    gx = next(n for n in w["nodes"] if n["name"] == "gx10")
    r = client.post(f"{base}/exclude", json={"node": gx["id"], "kind": "rehearsal", "minutes": 5}).json()
    assert gx["id"] in r["exclusions"] and r["decision"]["target"]["node_name"] == "spark2"
    assert any(e["kind"] == "rehearsal" for e in r["events"])
    assert client.post(f"{base}/include", json={"node": gx["id"]}).json()["exclusions"] == {}
    assert client.post(f"{base}/exclude", json={"node": gx["id"], "kind": "nope"}).status_code == 400
    d = client.get(f"{base}/doctor").json()
    assert any(c["id"] == "routing" for c in d["checks"])


@respx.mock
def test_toggle_routes_answer_with_the_state_after_the_change(client, hermes):  # noqa: F811
    boxes()
    base = "/api/plugins/local-fleet"
    on = client.post(f"{base}/private", json={"on": True}).json()
    assert on["private_only"] is True and on["private"]["in_force"] and "in force" in on["decision"]["reason"]
    assert client.post(f"{base}/private", json={"on": False}).json()["private_only"] is False
    assert client.post(f"{base}/keep", json={"on": True}).json()["keep_loaded"] is True
    client.post(f"{base}/use", json={"node": "best"})
    assert client.post(f"{base}/relinquish").json()["applied"] == {}
