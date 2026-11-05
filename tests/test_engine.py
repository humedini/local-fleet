"""Probe -> decide -> write config, end to end against a fake Hermes config and mocked boxes."""
import copy
import json
import sys
import types

import pytest
import respx

from local_fleet import cli, config_write, engine, slash, store, tools


@pytest.fixture
def hermes(tmp_path, monkeypatch):
    """Stand-ins for the two Hermes modules the plugin calls: config and plugin storage."""
    cfg = {"model": {"provider": "openai-codex", "default": "gpt-5.5", "context_length": 65536},
           "fallback_providers": [], "plugins": {"entries": {}}}
    writes = []

    def save_config(c, preserve_keys=None, merge_existing=False, **kw):
        writes.append(copy.deepcopy(c))
        if merge_existing:
            s = c["plugins"]["entries"]["local-fleet"]["settings"]
            cfg["plugins"]["entries"].setdefault("local-fleet", {"settings": {}})["settings"].update(s)
        else:
            cfg.clear()
            cfg.update(copy.deepcopy(c))

    conf = types.ModuleType("hermes_cli.config")
    conf.load_config = lambda: copy.deepcopy(cfg)
    conf.load_config_readonly = lambda: cfg
    conf.save_config = save_config
    storage = types.ModuleType("plugins.plugin_storage")
    storage.plugin_data_dir = lambda name: tmp_path
    for name, mod in {"hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.config": conf,
                      "plugins": types.ModuleType("plugins"), "plugins.plugin_storage": storage}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    store.bind(None)
    store.write_setting("cloud_model", "anthropic/claude-sonnet-4")
    store.write_setting("default_model", "qwen")
    f = store.fleet()
    f.add("gx10", "http://gx:11434/v1")
    f.add("spark2", "http://s2:11434/v1")
    return types.SimpleNamespace(cfg=cfg, writes=writes)


def boxes(gx=True, s2=True, gx_load=(), s2_load=("gemma",)):
    respx.reset()
    for host, up, loaded in (("gx", gx, gx_load), ("s2", s2, s2_load)):
        if up:
            respx.get(f"http://{host}:11434/v1/models").respond(json={"data": [{"id": "qwen"}, {"id": "gemma"}]})
            respx.get(f"http://{host}:11434/api/ps").respond(json={"models": [{"name": m} for m in loaded]})
            respx.post(f"http://{host}:11434/api/generate").respond(json={"done": True})
        else:
            respx.get(f"http://{host}:11434/v1/models").respond(status_code=502)


@respx.mock
def test_routes_to_freest_and_keeps_other_model_keys(hermes):
    boxes()
    d = engine.apply_policy()
    assert d["applied"] and d["target"]["node_name"] == "gx10"
    m = hermes.cfg["model"]
    assert m == {"provider": "custom", "default": "qwen", "base_url": "http://gx:11434/v1",
                 "api_mode": "chat_completions", "context_length": 65536}
    assert hermes.cfg["fallback_providers"] == [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}]
    assert store.load_state()["original_model"] == {"provider": "openai-codex", "default": "gpt-5.5"}


@respx.mock
def test_unchanged_route_writes_nothing_and_fallback_is_not_duplicated(hermes):
    boxes()
    engine.apply_policy()
    n = len(hermes.writes)
    d = engine.apply_policy()
    assert not d["applied"] and len(hermes.writes) == n
    assert len(hermes.cfg["fallback_providers"]) == 1


@respx.mock
def test_failover_then_failback(hermes):
    boxes()
    engine.apply_policy()
    boxes(gx=False, s2=False)
    d = engine.apply_policy()
    assert hermes.cfg["model"]["provider"] == "openrouter" and "base_url" not in hermes.cfg["model"]
    assert d["target"]["via"] == "failover"
    boxes(gx=False)
    d = engine.apply_policy()
    assert d["reason"] == "back on spark2 (it recovered)" and hermes.cfg["model"]["base_url"] == "http://s2:11434/v1"


@respx.mock
def test_no_cloud_target_leaves_primary_alone(hermes):
    store.write_setting("cloud_model", "")
    boxes(gx=False, s2=False)
    d = engine.apply_policy()
    assert not d["applied"] and "no cloud target" in d["warning"]
    assert hermes.cfg["model"]["provider"] == "openai-codex"


@respx.mock
def test_pin_and_restore(hermes):
    boxes()
    d = engine.apply_policy(pin="spark2")
    assert d["target"]["node_name"] == "spark2" and store.load_state()["applied"]["pinned"]
    assert engine.apply_policy()["target"]["node_name"] == "spark2"   # pin holds although gx10 is freer
    assert engine.apply_policy(unpin=True)["target"]["node_name"] == "gx10"
    engine.restore()
    assert hermes.cfg["model"] == {"provider": "openai-codex", "default": "gpt-5.5", "context_length": 65536}
    assert "applied" not in store.load_state()


@respx.mock
def test_dry_run_changes_nothing(hermes):
    boxes()
    engine.apply_policy(dry_run=True)
    assert hermes.cfg["model"]["provider"] == "openai-codex" and hermes.cfg["fallback_providers"] == []


@respx.mock
def test_slash_and_tools_return_text_and_json(hermes):
    boxes()
    assert "gx10" in slash.handle("status")
    assert slash.handle("mode nonsense").startswith("unknown mode")
    assert "least busy box: gx10" in slash.handle("use best")
    assert slash.handle("use nope").startswith("✗")
    out = json.loads(tools.fleet_status({}))
    assert out["ok"] and out["would_route_to"]["node_name"] == "gx10"
    assert all("api_key_env" not in n for n in json.loads(tools.fleet_list_nodes({}))["nodes"])
    assert not json.loads(tools.fleet_pull_model({"node": "gx10", "model": "bad tag; rm -rf"}))["ok"]


def test_tools_hidden_without_nodes(tmp_path, monkeypatch):
    storage = types.ModuleType("plugins.plugin_storage")
    storage.plugin_data_dir = lambda name: tmp_path
    monkeypatch.setitem(sys.modules, "plugins", types.ModuleType("plugins"))
    monkeypatch.setitem(sys.modules, "plugins.plugin_storage", storage)
    assert tools.fleet_ready() is False


def test_cli_parses_every_subcommand():
    import argparse
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    for argv in (["add", "--name", "a", "--url", "http://h:1/v1", "--label", "lan"], ["rm", "a"], ["list", "--json"],
                 ["status"], ["doctor"], ["watch", "--interval", "5", "--once"], ["use", "a"], ["use", "--freest"],
                 ["mode", "auto"], ["cloud", "openrouter", "x/y"], ["model", ""], ["endpoint"], ["restore"], ["setup"]):
        assert p.parse_args(argv).fleet_command == argv[0]
    with pytest.raises(SystemExit):
        p.parse_args(["mode", "fastest"])


@respx.mock
def test_series_and_history_feed_the_fleet_page(hermes):
    boxes()
    engine.apply_policy(dry_run=True)
    engine.apply_policy()
    boxes(gx=False, s2=False)
    engine.apply_policy()
    snap = engine.snapshot()
    assert all(len(v) == 3 for v in snap["series"].values())
    assert [e["kind"] for e in snap["history"]] == ["local", "cloud"]
    assert snap["history"][-1]["via"] == "failover"
    assert snap["primary"]["provider"] == "openrouter" and snap["local_model"] == "qwen"


@respx.mock
def test_privacy_hides_addresses_in_text_output(hermes):
    from local_fleet import render
    boxes()
    store.write_setting("hide_addresses", True)
    out = slash.handle("status")
    assert "http://" not in out and "(address hidden)" in out
    render.HIDE["on"] = False
