"""Other GPU work on a box (busy_urls) and the missed-probe grace (down_after_misses)."""
import json

import httpx
import pytest
import respx

from local_fleet import engine, events, store
from local_fleet.fleet import FleetError
from local_fleet.health import probe_all
from local_fleet.routing import check
from test_engine import boxes, hermes  # noqa: F401  (fixture)

GX = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama", "labels": [],
      "busy_urls": ["http://comfy-personal.example:8188/api/queue"]}
QUEUE = "http://comfy-personal.example:8188/api/queue"


def _up(host="gx", loaded=()):
    respx.get(f"http://{host}:11434/v1/models").respond(json={"data": [{"id": "qwen"}]})
    respx.get(f"http://{host}:11434/api/ps").respond(json={"models": [{"name": m} for m in loaded]})


@respx.mock
def test_comfyui_queue_with_work_marks_the_box_busy():
    _up()
    respx.get(QUEUE).respond(json={"queue_running": [[1, "x"]], "queue_pending": [[2, "y"], [3, "z"]]})
    snap = probe_all([GX], want="qwen")["a"]
    assert snap["status"] == "ok" and snap["busy"] is True
    assert snap["busy_detail"] == "comfy-personal: 1 running, 2 waiting"


@respx.mock
def test_empty_queue_down_server_or_generic_json():
    _up()
    respx.get(QUEUE).respond(json={"queue_running": [], "queue_pending": []})
    assert probe_all([GX])["a"]["busy"] is False
    respx.get(QUEUE).mock(side_effect=httpx.ConnectError("refused"))
    snap = probe_all([GX])["a"]
    assert snap["busy"] is False and snap["status"] == "ok"   # a server that is down runs nothing
    respx.get(QUEUE).respond(json={"busy": True, "detail": "ComfyUI work: 1 running, 0 waiting"})
    assert probe_all([GX])["a"]["busy_detail"] == "ComfyUI work: 1 running, 0 waiting"
    respx.get(QUEUE).respond(json={"busy": True})
    assert probe_all([GX])["a"]["busy_detail"] == "comfy-personal: busy"
    respx.get(QUEUE).respond(json={"busy": False, "detail": ""})
    assert probe_all([GX])["a"]["busy"] is False


@respx.mock
def test_no_busy_urls_means_no_busy_field_and_no_extra_request():
    _up()
    snap = probe_all([{k: v for k, v in GX.items() if k != "busy_urls"}])["a"]
    assert "busy" not in snap
    assert not any(c.request.url.host.startswith("comfy") for c in respx.calls)


@respx.mock
def test_busy_url_gets_no_node_credentials(monkeypatch):
    monkeypatch.setenv("GX_KEY", "secret")
    _up()
    route = respx.get(QUEUE).respond(json={"queue_running": [], "queue_pending": []})
    probe_all([dict(GX, api_key_env="GX_KEY")])
    assert "authorization" not in route.calls[0].request.headers


def test_busy_box_is_not_eligible():
    snap = {"status": "ok", "models": ["qwen"], "busy": True, "busy_detail": "comfy: 1 running, 0 waiting"}
    ok, why = check(GX, snap, "qwen")
    assert not ok and "busy with other GPU work" in why and "1 running" in why
    assert check(GX, dict(snap, busy=False), "qwen")[0]


def _comfy(busy):
    respx.get("http://comfy.example/api/queue").respond(
        json={"queue_running": [[1]] if busy else [], "queue_pending": []})


@respx.mock
def test_hermes_moves_off_a_box_when_comfyui_starts_and_frees_its_memory(hermes):  # noqa: F811
    store.fleet().update("gx10", busy_urls=["http://comfy.example/api/queue"])
    boxes(gx_load=(), s2_load=("gemma",))
    _comfy(False)
    d = engine.apply_policy()
    assert d["target"]["node_name"] == "gx10"
    # A render starts; qwen is in memory on gx10 from the warm-up.
    boxes(gx_load=("qwen",), s2_load=("gemma",))
    _comfy(True)
    gen = respx.post("http://gx:11434/api/generate").respond(json={"done": True})
    d = engine.apply_policy()
    assert d["target"]["node_name"] == "spark2"
    gx = next(c for c in d["candidates"] if c["name"] == "gx10")
    assert not gx["eligible"] and "busy" in gx["reason"]
    unload = [json.loads(c.request.content) for c in gen.calls]
    assert {"model": "qwen", "keep_alive": 0} in unload            # memory handed back now
    kinds = [e["kind"] for e in events.timeline(20)]
    assert "busy" in kinds
    # The render ends: gx10 is eligible again (spark2 is kept unless gx10 is clearly freer).
    boxes(gx_load=(), s2_load=("gemma",))
    _comfy(False)
    d = engine.apply_policy()
    assert next(c for c in d["candidates"] if c["name"] == "gx10")["eligible"]


@respx.mock
def test_no_unload_request_for_a_model_that_is_not_in_memory(hermes):  # noqa: F811
    store.fleet().update("gx10", busy_urls=["http://comfy.example/api/queue"])
    boxes(gx_load=(), s2_load=("gemma",))
    _comfy(False)
    store.write_setting("warm_before_switch", False)
    engine.apply_policy()
    boxes(gx_load=(), s2_load=("gemma",))     # qwen already unloaded on gx10
    _comfy(True)
    gen = respx.post("http://gx:11434/api/generate").respond(json={"done": True})
    engine.apply_policy()
    assert not gen.calls                       # keep_alive 0 on a model not loaded would load it


@respx.mock
def test_auto_bench_skips_a_busy_box(hermes, monkeypatch):  # noqa: F811
    store.fleet().update("gx10", busy_urls=["http://comfy.example/api/queue"])
    boxes()
    _comfy(True)
    benched = []
    monkeypatch.setattr(engine, "run_bench", lambda f, r, s, nodes, load=False: benched.extend(n["name"] for n in nodes) or {})
    engine.probe(auto_bench=True)
    assert "gx10" not in benched
    nodes, _ = engine.bench()
    assert [n["name"] for n in nodes] == ["spark2"]


@respx.mock
def test_one_missed_probe_does_not_move_hermes(hermes, monkeypatch):  # noqa: F811
    store.write_setting("down_after_misses", 2)
    boxes(s2_load=("gemma",))
    assert engine.apply_policy()["target"]["node_name"] == "gx10"
    boxes(gx=False)                                         # a blip
    d = engine.apply_policy()
    assert d["target"]["node_name"] == "gx10" and not d["changed"]
    h = store.fleet().get("gx10")["last_health"]
    assert h["status"] == "degraded" and h["misses"] == 1 and "missed 1 check" in h["detail"]
    assert not any(e["kind"] == "health" and "went down" in e["text"] for e in events.timeline(20))
    boxes()                                                 # back: the count resets
    engine.apply_policy()
    assert "misses" not in store.fleet().get("gx10")["last_health"]


@respx.mock
def test_two_missed_probes_count_as_down(hermes, monkeypatch):  # noqa: F811
    store.write_setting("down_after_misses", 2)
    monkeypatch.setattr(engine, "MISS_FLOOR_S", 0)
    boxes(s2_load=("gemma",))
    engine.apply_policy()
    boxes(gx=False)
    engine.apply_policy()
    boxes(gx=False)
    d = engine.apply_policy()
    assert d["target"]["node_name"] == "spark2"
    assert store.fleet().get("gx10")["last_health"]["status"] == "down"


@respx.mock
def test_misses_close_together_wait_for_the_floor(hermes):  # noqa: F811
    store.write_setting("down_after_misses", 2)
    boxes(s2_load=("gemma",))
    engine.apply_policy()
    for _ in range(3):                                      # Desktop probing every few seconds
        boxes(gx=False)
        d = engine.apply_policy()
    assert d["target"]["node_name"] == "gx10"
    assert store.fleet().get("gx10")["last_health"]["misses"] == 3


@respx.mock
def test_a_box_that_was_already_down_gets_no_grace(hermes):  # noqa: F811
    store.write_setting("down_after_misses", 2)
    boxes(gx=False)
    engine.probe()
    assert store.fleet().get("gx10")["last_health"]["status"] == "down"


def test_busy_url_validation(hermes):  # noqa: F811
    f = store.fleet()
    assert f.update("gx10", busy_urls=["http://gx:8188/api/queue"])["busy_urls"] == ["http://gx:8188/api/queue"]
    assert f.update("gx10", busy_urls=[""])["busy_urls"] is None
    for bad in ("ftp://gx/q", "http://user:pw@gx/q", "gx:8188"):
        with pytest.raises(FleetError):
            f.update("gx10", busy_urls=[bad])
