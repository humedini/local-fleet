"""Probe -> decide -> write config, end to end against a fake Hermes config and mocked boxes."""
import copy
import re
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

    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = copy.deepcopy(v)

    def save_config(c, preserve_keys=None, merge_existing=False, **kw):
        writes.append(copy.deepcopy(c))
        if merge_existing:
            merge(cfg, c)
        else:
            cfg.clear()
            cfg.update(copy.deepcopy(c))

    env = {}

    def expand(o):  # Hermes's load_config expands ${VAR}; read_raw_config does not
        if isinstance(o, str):
            return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: env.get(m.group(1), m.group(0)), o)
        if isinstance(o, dict):
            return {k: expand(v) for k, v in o.items()}
        if isinstance(o, list):
            return [expand(v) for v in o]
        return o

    conf = types.ModuleType("hermes_cli.config")
    conf.load_config = lambda: expand(copy.deepcopy(cfg))
    conf.read_raw_config = lambda: copy.deepcopy(cfg)
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
    return types.SimpleNamespace(cfg=cfg, writes=writes, env=env)


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


@respx.mock
def test_auto_pick_clears_a_pin_even_when_the_box_stays_the_same(hermes):
    boxes()                                         # gx10 is the least busy
    engine.apply_policy(pin="gx10")
    assert store.load_state()["applied"]["pinned"] is True
    d = engine.apply_policy(unpin=True)             # auto-pick also lands on gx10: nothing to rewrite...
    assert d["target"]["node_name"] == "gx10"
    assert "pinned" not in store.load_state()["applied"]   # ...but the pin must still go
    boxes(gx_load=("a", "b", "c", "d"))             # gx10 becomes clearly busier
    assert engine.apply_policy()["target"]["node_name"] == "spark2"


@respx.mock
def test_pinning_the_current_box_records_the_pin_without_rewriting_config(hermes):
    boxes()
    engine.apply_policy()                           # routed to gx10 automatically
    n = len(hermes.writes)
    engine.apply_policy(pin="gx10")
    assert store.load_state()["applied"]["pinned"] is True and len(hermes.writes) == n


@respx.mock
def test_a_manual_primary_change_pauses_routing(hermes):
    boxes()
    engine.apply_policy()                                       # routed to gx10
    hermes.cfg["model"] = {"provider": "anthropic", "default": "claude-x"}   # the user switches by hand
    d = engine.apply_policy()
    assert "outside Local Fleet" in d["warning"] and not d["applied"]
    assert hermes.cfg["model"]["provider"] == "anthropic"       # left alone
    assert not store.load_state().get("applied")
    assert engine.apply_policy()["applied"] is False            # still paused
    engine.apply_policy(unpin=True)                             # Auto-pick resumes
    assert hermes.cfg["model"]["base_url"] == "http://gx:11434/v1"


@respx.mock
def test_snapshot_export_is_complete_and_honours_privacy(hermes, capsys):
    import argparse
    boxes()
    engine.apply_policy()
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    cli.main(p.parse_args(["snapshot"]))
    snap = json.loads(capsys.readouterr().out)
    assert snap["schema"] == 1 and snap["applied"]["node_name"] == "gx10" and len(snap["nodes"]) == 2
    assert all("api_key_env" not in n for n in snap["nodes"])
    store.write_setting("hide_addresses", True)
    cli.main(p.parse_args(["snapshot"]))
    out = capsys.readouterr().out
    assert "http://" not in out


@respx.mock
def test_privacy_covers_errors_and_json_outputs(hermes, capsys):
    import argparse
    from local_fleet import render
    boxes()
    store.write_setting("hide_addresses", True)
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    try:
        cli.main(p.parse_args(["add", "--name", "dup", "--url", "http://gx:11434/v1"]))   # duplicate address
    except SystemExit:
        pass
    try:
        cli.main(p.parse_args(["add", "--name", "bad", "--url", "ftp://10.1.2.3/x"]))     # invalid address
    except SystemExit:
        pass
    cli.main(p.parse_args(["list", "--json"]))
    cli.main(p.parse_args(["status", "--json"]))
    out = capsys.readouterr().out
    assert "already registered as" in out and "<address>" in out
    for leak in ("http://", "gx:11434", "10.1.2.3"):
        assert leak not in out, leak
    render.HIDE["on"] = False
