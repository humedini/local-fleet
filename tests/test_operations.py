"""Decision inspector, rehearsal and maintenance, readiness, flight recorder."""
import json
from datetime import datetime, timedelta, timezone

import respx

from local_fleet import engine, events, readiness, store, traffic
from local_fleet.routing import check, decide
from test_engine import boxes, hermes  # noqa: F401  (fixture)

GX = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama", "labels": []}
S2 = {"id": "b", "name": "spark2", "base_url": "http://s2:11434/v1", "kind": "ollama", "labels": []}


def snap(load=0.0, models=("qwen",), status="ok"):
    return {"status": status, "load_proxy": load, "latency_ms": 5, "models": list(models), "resident": [], "free_vram_approx": None}


SET = {"mode": "auto", "default_model": "qwen", "cloud_provider": "openrouter", "cloud_model": "big"}


def test_candidates_explain_every_box():
    d = decide(SET, [GX, S2], {"a": snap(0.5), "b": snap(0.0, models=("other",))}, {})
    by = {c["name"]: c for c in d["candidates"]}
    assert by["gx10"]["chosen"] and by["gx10"]["eligible"] and by["gx10"]["score"]
    assert not by["spark2"]["eligible"] and by["spark2"]["reason"] == "does not have qwen"
    assert d["candidates"][0]["name"] == "gx10"            # eligible first


def test_exclusions_and_verified_unsuitability():
    until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert "rehearsal" in check(GX, snap(), "qwen", {"a": {"kind": "rehearsal", "until": until}})[1]
    assert check(GX, snap(), "qwen", {"a": {"kind": "maintenance"}})[1].startswith("maintenance")
    no_tools = dict(GX, caps={"qwen": {"tools": False, "source": "verified: Ollama /api/show"}})
    assert check(no_tools, snap(), "qwen") == (False, "no tool calling (verified)")
    small = dict(GX, caps={"qwen": {"tools": True, "context": 4096, "context_source": "running context (/api/ps)", "source": "verified"}})
    assert not check(small, snap(), "qwen", None, 32768)[0]
    unknown = dict(GX, caps={"qwen": {"tools": None, "source": "vllm does not report capabilities"}})
    assert check(unknown, snap(), "qwen")[0]               # unknown is never a rejection


@respx.mock
def test_readiness_reads_ollama_show():
    respx.post("http://gx:11434/api/show").respond(json={"capabilities": ["completion", "tools"], "parameters": "num_ctx    65536\ntemperature 1"})
    import httpx
    with httpx.Client() as c:
        caps = readiness.inspect(c, GX, "qwen")
    assert caps["tools"] is True and caps["vision"] is False and caps["context"] == 65536
    assert caps["source"].startswith("verified")


@respx.mock
def test_rehearsal_moves_the_route_and_expires(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()                                   # routed to gx10
    d = engine.exclude("gx10", "rehearsal", minutes=10)
    assert d["target"]["node_name"] == "spark2"
    assert any(e["kind"] == "rehearsal" for e in events.load())
    state = store.load_state()                              # expire it
    state["exclusions"][next(iter(state["exclusions"]))]["until"] = "2000-01-01T00:00:00+00:00"
    store.save_state(state)
    boxes(s2_load=("x", "y", "z", "w"))
    d = engine.apply_policy()
    assert d["target"]["node_name"] == "gx10" and not store.load_state()["exclusions"]
    assert any("rehearsal ended" in e["text"] for e in events.load())


@respx.mock
def test_maintenance_never_routes_if_routing_is_off(hermes):  # noqa: F811
    boxes()
    engine.exclude("gx10", "maintenance")
    assert hermes.cfg["model"]["provider"] == "openai-codex"    # routing was never turned on
    assert engine.apply_policy(dry_run=True)["target"]["node_name"] == "spark2"
    engine.include("gx10")
    assert not store.load_state()["exclusions"]


@respx.mock
def test_flight_recorder_separates_configured_and_served(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()
    gx = store.fleet().find("gx10")
    traffic.on_post_api_request(base_url=gx["base_url"], provider="custom", model="qwen", api_duration=1,
                                usage={"prompt_tokens": 10, "completion_tokens": 40})
    traffic.on_post_api_request(base_url="https://openrouter.ai/api/v1", provider="openrouter", model="big", api_duration=1,
                                usage={"prompt_tokens": 10, "completion_tokens": 40})      # core fallback took over
    tl = events.timeline()
    kinds = [e["kind"] for e in tl]
    assert "route" in kinds and kinds.count("served") == 2
    assert tl[-1]["text"].startswith("served by cloud · openrouter")
    assert json.dumps(tl)


@respx.mock
def test_drift_is_detected_never_fought_and_resolvable(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()
    assert hermes.cfg["fallback_providers"]
    hermes.cfg["fallback_providers"] = []                    # another plugin removes our cloud entry
    engine.apply_policy()
    assert hermes.cfg["fallback_providers"] == []            # not silently re-added
    assert [d["what"] for d in engine.drift()] == ["fallback"]
    engine.reapply()
    assert hermes.cfg["fallback_providers"] and not engine.drift()
    hermes.cfg["model"] = {"provider": "anthropic", "default": "x"}
    engine.apply_policy()
    assert "primary" in [d["what"] for d in engine.drift()]
    engine.relinquish()
    assert hermes.cfg["model"] == {"provider": "anthropic", "default": "x"}
    assert engine.apply_policy()["applied"] is False         # stays hands-off


@respx.mock
def test_side_task_drift_pauses_following(hermes):  # noqa: F811
    store.write_setting("aux_tasks", ["compression"])
    boxes()
    engine.apply_policy(dry_run=True, aux_follow=True)
    hermes.cfg["auxiliary"]["compression"]["base_url"] = "http://elsewhere:1/v1"
    d = engine.apply_policy(dry_run=True, aux_follow=True)
    assert "paused" in d["aux"] and hermes.cfg["auxiliary"]["compression"]["base_url"] == "http://elsewhere:1/v1"
    assert "side tasks" in [x["what"] for x in engine.drift()]


def test_savings_breakdown_is_auditable():
    lines = [{"t": 1, "n": "a", "in": 1000, "out": 500, "ok": 1, "d": 1},
             {"t": 2, "n": "a", "in": 0, "out": 0, "ok": 1, "d": 1},             # no usage reported
             {"t": 3, "n": "a", "in": 200, "out": 100, "ok": 1, "d": 1, "aux": "compression"},
             {"t": 4, "n": None, "p": "openrouter", "in": 999, "out": 999, "ok": 1, "d": 1}]
    t = traffic.summarize(lines, (3.0, 15.0), now=5)
    b = t["breakdown"]
    assert b["local_in"] == 1200 and b["local_out"] == 600 and b["aux_in"] == 200
    assert b["calls_local"] == 3 and b["calls_local_counted"] == 2 and b["coverage"] == round(2 / 3, 3)
    assert t["saved"] == round(b["saved_in"] + b["saved_out"], 2)
    assert "not profit" in b["caveat"]


@respx.mock
def test_doctor_checks_have_fixes(hermes):  # noqa: F811
    from local_fleet import doctor
    boxes(gx=False)
    store.write_setting("cloud_model", "")
    items = doctor.checks()
    by = {c["id"].split(":")[0]: c for c in items}
    assert by["down"]["level"] == "error" and by["down"]["fix"]["action"] == "probe"
    assert by["cloud"]["fix"]["command"].startswith("hermes fleet cloud")
    assert by["routing"]["fix"]["action"] == "use"
    ok, lines = doctor.run()
    assert not ok and any("fix:" in l for l in lines)
