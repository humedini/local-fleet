"""Traffic stats, subagent spreading, side tasks and warm-up."""
import json
import time

import respx

from local_fleet import aux, delegation, engine, store, traffic
from local_fleet.warm import warm
from test_engine import boxes, hermes  # noqa: F401  (fixture)

GX = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama", "labels": []}
S2 = {"id": "b", "name": "spark2", "base_url": "http://s2:11434/v1", "kind": "ollama", "labels": []}


def health(load=0.0, models=("qwen",), status="ok"):
    return {"status": status, "load_proxy": load, "latency_ms": 5, "models": list(models), "resident": [], "free_vram_approx": None}


def test_traffic_matches_boxes_and_never_keeps_content(hermes):  # noqa: F811
    gx = store.fleet().nodes[0]
    traffic.on_post_api_request(base_url=gx["base_url"] + "/", provider="custom", model="qwen", api_duration=2.0,
                                usage={"prompt_tokens": 100, "completion_tokens": 50}, session_id="s1",
                                request={"messages": ["secret"]}, response={"text": "secret"})
    traffic.on_api_request_error(base_url=gx["base_url"], provider="custom", model="qwen", api_duration=0.1)
    traffic.on_post_auxiliary_call(base_url="https://openrouter.ai/api/v1", provider="openrouter", model="x",
                                   aux_task="title_generation", usage={"input_tokens": 10, "output_tokens": 5}, api_duration=1)
    raw = (store.data_dir() / "traffic.jsonl").read_text()
    assert "secret" not in raw
    t = traffic.summarize(traffic.load(), (3.0, 15.0))
    b = t["boxes"][gx["id"]]
    assert (b["calls"], b["errors"], b["tps"], b["live"]) == (2, 1, 25.0, 2)
    assert t["local_tokens"] == 150 and t["cloud_tokens"] == 15
    assert t["saved"] == round((100 * 3 + 50 * 15) / 1e6, 2)


def test_traffic_recording_never_raises(monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: (_ for _ in ()).throw(OSError("disk")))
    traffic.on_post_api_request(base_url="x")


def test_fanout_spreads_tasks_across_boxes_freest_first():
    settings = {"default_model": "qwen", "cloud_provider": "openrouter", "cloud_model": "big"}
    nodes = [dict(GX, last_health=health(0.25)), dict(S2, last_health=health(0.0))]
    delegation._turn.update(at=0.0, i=0)
    got = [delegation.route({}, settings, nodes)["label"] for _ in range(3)]
    assert got == ["spark2", "gx10", "spark2"]
    r = delegation.route({}, settings, nodes)
    assert r["provider"] == "custom" and r["fallback_providers"] == [{"provider": "openrouter", "model": "big"}]
    assert delegation.route({"where": "cloud"}, settings, nodes) == {"provider": "openrouter", "model": "big", "label": "cloud"}


def test_fanout_counter_restarts_after_a_pause(monkeypatch):
    settings = {"default_model": "qwen"}
    nodes = [dict(GX, last_health=health(0.25)), dict(S2, last_health=health(0.0))]
    delegation._turn.update(at=time.monotonic() - 60, i=5)
    assert delegation.route({}, settings, nodes)["label"] == "spark2"


def test_no_healthy_box_means_cloud_or_refusal():
    settings = {"default_model": "qwen", "cloud_provider": "openrouter", "cloud_model": "big"}
    nodes = [dict(GX, last_health=health(status="down"))]
    assert delegation.route({}, settings, nodes)["label"].startswith("cloud")
    try:
        delegation.route({"where": "local"}, settings, nodes)
        raise AssertionError("expected a refusal")
    except LookupError:
        pass


@respx.mock
def test_side_tasks_follow_the_freest_box_and_restore(hermes):  # noqa: F811
    hermes.cfg["auxiliary"] = {"compression": {"timeout": 120, "provider": "openrouter", "model": "cheap"}}
    store.write_setting("aux_tasks", ["title_generation", "compression"])
    boxes()
    d = engine.apply_policy()
    comp = hermes.cfg["auxiliary"]["compression"]
    assert d["aux"].startswith("side tasks → gx10")
    assert comp["base_url"] == "http://gx:11434/v1" and comp["provider"] == "ollama" and comp["timeout"] == 120
    assert comp["fallback_chain"] == [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}]
    assert engine.apply_policy()["aux"] is None          # unchanged: no rewrite
    engine.aux_off()
    assert hermes.cfg["auxiliary"]["compression"] == {"timeout": 120, "provider": "openrouter", "model": "cheap"}
    assert "base_url" not in hermes.cfg["auxiliary"]["title_generation"]


@respx.mock
def test_warm_loads_only_when_not_in_memory():
    route = respx.post("http://gx:11434/api/generate").respond(json={"done": True})
    assert warm(GX, "qwen", ["qwen"])["detail"] == "already in memory"
    assert warm(dict(GX, kind="vllm"), "qwen", [])["warmed"] is False
    assert warm(GX, "qwen", [])["warmed"] is True
    assert json.loads(route.calls.last.request.content) == {"model": "qwen", "keep_alive": "30m"}


def test_aux_block_shape():
    b = aux.block(dict(GX, kind="vllm"), "m", "", "")
    assert b == {"provider": "vllm", "model": "m", "base_url": "http://gx:11434/v1"}


def test_currency_codes_and_formatting():
    assert store.currency_code("£") == "GBP" and store.currency_code("eur") == "EUR"
    for bad in ("pounds", "12", ""):
        try:
            store.currency_code(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert store.format_money(2.5, "GBP") == "£2.50"
    assert store.format_money(1234.5, "EUR") == "€1,234"
    assert store.format_money(3.1, "PLN") == "3.10 PLN"
    assert store.format_money(42.4, "JPY") == "¥42"


def test_old_symbol_setting_reads_as_a_code(hermes):  # noqa: F811
    store.write_setting("currency", "£")
    assert store.read_settings()["currency"] == "GBP"


@respx.mock
def test_session_start_refresh_never_routes_until_opted_in(hermes):  # noqa: F811
    import local_fleet as plugin
    boxes()
    plugin._refresh_on_session_start(session_id="s")
    for _ in range(50):
        if plugin._bg.acquire(blocking=False):
            plugin._bg.release()
            break
        time.sleep(0.05)
    assert hermes.cfg["model"]["provider"] == "openai-codex"          # untouched
    assert "applied" not in store.load_state() and store.load_state().get("last_probe_at")


@respx.mock
def test_aux_on_leaves_the_main_route_alone(hermes):  # noqa: F811
    store.write_setting("aux_tasks", ["compression"])
    boxes()
    d = engine.apply_policy(dry_run=True, aux_follow=True)
    assert d["aux"].startswith("side tasks")
    assert hermes.cfg["model"]["provider"] == "openai-codex"
    assert hermes.cfg["auxiliary"]["compression"]["base_url"] == "http://gx:11434/v1"


@respx.mock
def test_keep_loaded_holds_the_routed_model_and_releases_it(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()                                   # routed to gx10, keep off: no keep_alive -1
    store.write_setting("keep_loaded", True)
    engine.apply_policy()
    calls = [json.loads(c.request.content) for c in respx.calls if c.request.url.path == "/api/generate"]
    assert any(c.get("keep_alive") == -1 and c["model"] == "qwen" for c in calls)   # a number, not "-1"
    assert store.load_state()["applied"]["kept"] is True
    respx.calls.reset()
    engine.set_keep(False)                                  # hands it back to a normal timer
    calls = [json.loads(c.request.content) for c in respx.calls if c.request.url.path == "/api/generate"]
    assert any(c.get("keep_alive") == "5m" for c in calls)
