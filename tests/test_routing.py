import pytest

from local_fleet.routing import decide, model_for

GX = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama", "labels": []}
S2 = {"id": "b", "name": "spark2", "base_url": "http://s2:11434/v1", "kind": "ollama", "labels": []}
NODES = [GX, S2]
CLOUD = {"cloud_provider": "openrouter", "cloud_model": "anthropic/claude-sonnet-4"}


def snap(status="ok", load=0.0, models=("qwen", "gemma"), resident=()):
    return {"status": status, "load_proxy": load, "latency_ms": 10, "models": list(models),
            "resident": list(resident), "free_vram_approx": None}


def settings(**kw):
    return {"mode": "auto", "default_model": "qwen", "failback_enabled": True, **CLOUD, **kw}


UP = {"a": snap(load=0.25), "b": snap(load=0.0)}
DOWN = {"a": snap(status="down"), "b": snap(status="down")}


@pytest.mark.parametrize("mode", ["auto", "prefer-local"])
def test_local_modes_pick_freest(mode):
    d = decide(settings(mode=mode), NODES, UP, {})
    assert d["target"]["kind"] == "local" and d["target"]["node_name"] == "spark2"
    assert d["target"]["model"] == "qwen" and d["changed"]


@pytest.mark.parametrize("mode", ["auto", "prefer-local"])
def test_all_down_fails_over_to_cloud(mode):
    d = decide(settings(mode=mode), NODES, DOWN, {"kind": "local", "node_id": "b", "model": "qwen"})
    t = d["target"]
    assert t["kind"] == "cloud" and t["provider"] == "openrouter" and t["via"] == "failover"
    assert d["healthy_locals"] == []


def test_prefer_cloud_ignores_healthy_locals():
    d = decide(settings(mode="prefer-cloud"), NODES, UP, {})
    assert d["target"]["kind"] == "cloud" and d["freest_node_id"] == "b"


def test_failback_when_a_local_recovers():
    cur = {"kind": "cloud", "provider": "openrouter", "model": CLOUD["cloud_model"], "via": "failover"}
    d = decide(settings(), NODES, UP, cur)
    assert d["target"]["kind"] == "local" and d["reason"].startswith("failback")


def test_failback_disabled_stays_on_cloud():
    cur = {"kind": "cloud", "provider": "openrouter", "model": CLOUD["cloud_model"], "via": "failover"}
    d = decide(settings(failback_enabled=False), NODES, UP, cur)
    assert d["target"]["kind"] == "cloud" and not d["changed"]


def test_manual_cloud_is_not_treated_as_failover():
    # prefer-cloud applied cloud (no "via"); switching to auto moves to a local even with failback off
    cur = {"kind": "cloud", "provider": "openrouter", "model": CLOUD["cloud_model"]}
    assert decide(settings(failback_enabled=False), NODES, UP, cur)["target"]["kind"] == "local"


def test_sticks_to_active_node_inside_the_margin():
    cur = {"kind": "local", "node_id": "a", "model": "qwen"}
    d = decide(settings(), NODES, UP, cur)          # gx10 0.25 vs spark2 0.0: under the 0.25 margin
    assert d["target"]["node_name"] == "gx10" and not d["changed"]
    busy = {"a": snap(load=0.75), "b": snap(load=0.0)}
    assert decide(settings(), NODES, busy, cur)["target"]["node_name"] == "spark2"


def test_moves_off_active_node_when_it_goes_down():
    cur = {"kind": "local", "node_id": "a", "model": "qwen"}
    res = {"a": snap(status="down"), "b": snap(load=0.5)}
    assert decide(settings(), NODES, res, cur)["target"]["node_name"] == "spark2"


def test_pin_survives_prefer_cloud_and_load_until_the_node_dies():
    cur = {"kind": "local", "node_id": "a", "model": "qwen", "pinned": True}
    busy = {"a": snap(load=1.0), "b": snap(load=0.0)}
    assert decide(settings(mode="prefer-cloud"), NODES, busy, cur)["target"]["node_name"] == "gx10"
    res = {"a": snap(status="down"), "b": snap()}
    assert decide(settings(), NODES, res, cur)["target"]["node_name"] == "spark2"


def test_wanted_model_missing_everywhere_means_cloud():
    d = decide(settings(default_model="llama-405b"), NODES, UP, {})
    assert d["target"]["kind"] == "cloud" and "llama-405b" in d["reason"]


def test_disabled_nodes_are_never_chosen():
    nodes = [dict(GX, enabled=False), S2]
    res = {"a": snap(load=0.0), "b": snap(load=0.9)}
    assert decide(settings(), nodes, res, {})["target"]["node_name"] == "spark2"


def test_model_choice_without_a_default():
    s = snap(models=("mxbai-embed-large", "gemma", "qwen"), resident=("qwen",))
    assert model_for(GX, s, "", "") == "qwen"              # already in memory
    assert model_for(GX, s, "", "gemma") == "gemma"        # keep the current one
    assert model_for(GX, snap(models=("mxbai-embed-large", "gemma")), "", "") == "gemma"  # never an embedder
