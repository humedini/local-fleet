"""Clusters (several boxes behind one endpoint) and display names."""
import pytest
import respx

from local_fleet import engine, store
from local_fleet.fleet import Fleet, FleetError, display_name
from test_engine import hermes  # noqa: F401  (fixture)


def test_cluster_rules(tmp_path):
    f = Fleet(tmp_path)
    a = f.add("spark-a", "http://10.0.0.21:11434/v1")
    b = f.add("spark-b", "http://10.0.0.22:11434/v1")
    c = f.add("pair", "http://10.0.0.21:8000/v1", "vllm", members=["spark-a", "SPARK-B"], link=" 200  GbE ")
    assert c["members"] == [a["id"], b["id"]] and c["link"] == "200 GbE"
    with pytest.raises(FleetError):
        f.add("solo", "http://10.0.0.23:8000/v1", members=["spark-a"])            # needs two
    with pytest.raises(FleetError):
        f.add("nest", "http://10.0.0.24:8000/v1", members=["pair", "spark-a"])    # no clusters in clusters
    with pytest.raises(FleetError):
        f.remove("spark-a")                                                       # still a member
    f.remove("pair")
    f.remove("spark-a")


def test_display_names(tmp_path):
    f = Fleet(tmp_path)
    n = f.add("gx10", "http://h:1/v1", title="  Big   Spark ")
    assert n["title"] == "Big Spark" and display_name(n) == "Big Spark"
    f.update("gx10", title="")
    assert f.get("gx10")["title"] is None and display_name(f.get("gx10")) == "gx10"
    with pytest.raises(FleetError):
        f.update("gx10", title="x" * 41)


@respx.mock
def test_a_busy_cluster_makes_its_members_busy(hermes):  # noqa: F811
    f = store.fleet()
    gx, s2 = f.nodes
    f.add("pair", "http://head:8000/v1", "vllm", members=[gx["id"], s2["id"]])
    for host in ("gx", "s2"):
        respx.get(f"http://{host}:11434/v1/models").respond(json={"data": [{"id": "qwen"}]})
        respx.get(f"http://{host}:11434/api/ps").respond(json={"models": []})
        respx.get(f"http://{host}:11434/api/version").respond(json={"version": "0.13.4"})
    respx.get("http://head:8000/v1/models").respond(json={"data": [{"id": "big"}]})
    respx.get("http://head:8000/metrics").respond(text="vllm:kv_cache_usage_perc 0.8\n")
    _, _, results = engine.probe()
    assert results[gx["id"]]["load_proxy"] == 0.8 and results[gx["id"]]["in_cluster"] == "pair"
    assert results[s2["id"]]["version"] == "0.13.4"


def test_rename_route(hermes):  # noqa: F811
    import importlib.util
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    api = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("lf_api_rename", api)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = FastAPI()
    app.include_router(mod.router, prefix="/p")
    c = TestClient(app)
    r = c.post("/p/rename", json={"node": "gx10", "title": "Big Spark"})
    assert r.status_code == 200 and next(n for n in r.json()["nodes"] if n["name"] == "gx10")["title"] == "Big Spark"
    assert c.post("/p/rename", json={"node": "gx10", "title": "y" * 50}).status_code == 400
