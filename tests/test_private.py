"""Private inference transitions, asserted on the resulting Hermes config (what Hermes would actually
call), not on refusal messages or badges. The fake config starts with a cloud primary (openai-codex)."""
import json

import respx

from local_fleet import delegation, engine, events, store
from test_engine import boxes, hermes  # noqa: F401  (fixture)

CLOUD = {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}


def _no_cloud_anywhere(cfg):
    """Every route Hermes could take for a model call, per private.py's scope, is a registered box."""
    local = ("http://gx:11434/v1", "http://s2:11434/v1")
    assert cfg["model"]["provider"] == "custom" and cfg["model"]["base_url"] in local, cfg["model"]
    for e in cfg.get("fallback_providers") or []:
        assert e.get("base_url") in local or e.get("provider") in (cfg.get("providers") or {}), e
    for t, b in (cfg.get("auxiliary") or {}).items():
        assert b.get("base_url") in local or (b.get("provider") or "auto") in ("auto", "main"), (t, b)
        assert not b.get("fallback_chain"), (t, b)


@respx.mock
def test_enable_with_a_cloud_primary_takes_routing_and_fails_closed_when_boxes_go(hermes):  # noqa: F811
    hermes.cfg["fallback_providers"] = [dict(CLOUD)]
    boxes()
    assert not store.load_state().get("applied")                 # routing was off: Hermes on its cloud primary
    msg = engine.set_private(True)
    assert "in force" in msg and "NOT" not in msg, msg
    _no_cloud_anywhere(hermes.cfg)
    assert hermes.cfg["fallback_providers"] == []
    boxes(gx=False, s2=False)                                    # every box goes
    d = engine.apply_policy()
    assert d["target"]["kind"] == "refused" and "refuses cloud" in d["warning"]
    _no_cloud_anywhere(hermes.cfg)                               # primary still on a box: calls fail, never cloud
    assert engine.private_status()["in_force"]
    boxes()                                                      # a box is back: Hermes resumes on it
    d = engine.apply_policy()
    assert d["target"]["kind"] == "local"
    _no_cloud_anywhere(hermes.cfg)


@respx.mock
def test_enable_while_every_box_is_down_moves_a_cloud_primary_onto_a_box(hermes):  # noqa: F811
    boxes(gx=False, s2=False)
    msg = engine.set_private(True)
    assert hermes.cfg["model"]["provider"] == "custom" and hermes.cfg["model"]["base_url"] == "http://gx:11434/v1"
    assert hermes.cfg["model"]["default"] == "qwen"
    assert "refuses cloud" in msg
    assert any(e["kind"] == "refused" and "held on" in e["text"] for e in events.load())
    assert store.load_state()["original_model"] == {"provider": "openai-codex", "default": "gpt-5.5"}
    engine.set_private(False)                                    # off, still no box: cloud is allowed again
    assert hermes.cfg["model"]["provider"] == "openrouter"


@respx.mock
def test_managed_side_tasks_lose_their_cloud_fallback_without_pausing(hermes):  # noqa: F811
    store.write_setting("aux_tasks", ["title_generation", "compression"])
    boxes()
    engine.apply_policy()                                        # routed; side tasks carry a cloud fallback_chain
    assert hermes.cfg["auxiliary"]["compression"]["fallback_chain"] == [CLOUD]
    assert CLOUD in hermes.cfg["fallback_providers"]
    engine.set_private(True)
    st = store.load_state()
    assert not st.get("aux_paused") and st["aux_applied"]["block"].get("fallback_chain") is None
    _no_cloud_anywhere(hermes.cfg)
    assert engine.drift() == []                                  # removing our own cloud entry is not drift
    boxes(gx=False, s2=False)
    engine.apply_policy()
    _no_cloud_anywhere(hermes.cfg)                               # side tasks held on their box, not handed back
    assert hermes.cfg["auxiliary"]["compression"]["base_url"] == "http://gx:11434/v1"
    boxes()
    engine.set_private(False)                                    # off: cloud fallback back on side tasks and the chain
    assert hermes.cfg["auxiliary"]["compression"]["fallback_chain"] == [CLOUD]
    assert CLOUD in hermes.cfg["fallback_providers"]


@respx.mock
def test_unmanaged_literal_key_cloud_side_task_is_reported_never_stored(hermes):  # noqa: F811
    hermes.cfg["auxiliary"] = {"vision": {"provider": "openrouter", "model": "vis", "api_key": "sk-PRIVATE-9"}}
    boxes()
    msg = engine.set_private(True)
    st = engine.private_status()
    assert not st["in_force"] and "NOT fully in force" in msg
    assert any(p["what"] == "side tasks" and "auxiliary.vision" in p["detail"] for p in st["problems"])
    assert hermes.cfg["auxiliary"]["vision"]["api_key"] == "sk-PRIVATE-9"     # not ours: left alone
    assert "sk-PRIVATE-9" not in msg + json.dumps(engine.snapshot())
    for f in store.data_dir().rglob("*"):
        if f.is_file():
            assert "sk-PRIVATE-9" not in f.read_text(errors="ignore"), f
    from local_fleet import doctor
    c = next(c for c in doctor.checks() if c["id"] == "private")
    assert c["level"] == "error" and "auxiliary.vision" in c["detail"] and "sk-" not in c["detail"]


@respx.mock
def test_subagents_move_to_the_fleet_backend_and_back_unless_changed_meanwhile(hermes):  # noqa: F811
    hermes.cfg["delegation"] = {"backend": "default"}
    boxes()
    engine.set_private(True)
    assert hermes.cfg["delegation"]["backend"] == "fleet" and engine.private_status()["in_force"]
    s = store.read_settings()
    for task in ({"where": "cloud"}, {}):                        # with no box, fleet routing refuses cloud
        try:
            delegation.route(task, s, [dict(n, last_health={"status": "down"}) for n in store.fleet().nodes])
            raise AssertionError("expected a refusal")
        except LookupError as e:
            assert "private" in str(e) or "refuses cloud" in str(e)
    r = delegation.route({}, s, store.fleet().nodes)
    assert r["fallback_providers"] == [] and r["base_url"].startswith("http://")
    hermes.cfg["delegation"]["backend"] = "other"                # another writer picks a backend we cannot hold
    st = engine.private_status()
    assert not st["in_force"] and any(p["what"] == "subagents" for p in st["problems"])
    msg = engine.set_private(False)
    assert hermes.cfg["delegation"]["backend"] == "other" and "changed since" in msg   # not fought over

    hermes.cfg["delegation"]["backend"] = "default"
    engine.set_private(True)
    engine.set_private(False)
    assert hermes.cfg["delegation"]["backend"] == "default"


@respx.mock
def test_restore_never_duplicates_and_external_cloud_edits_are_reported_not_fought(hermes):  # noqa: F811
    hermes.cfg["fallback_providers"] = [dict(CLOUD), {"provider": "nous", "model": "h4"}]
    boxes()
    engine.set_private(True)
    assert hermes.cfg["fallback_providers"] == []
    hermes.cfg["fallback_providers"].append({"provider": "nous", "model": "h4"})   # someone re-adds a cloud entry
    st = engine.private_status()
    assert not st["in_force"] and any("nous/h4" in p["detail"] for p in st["problems"])
    engine.apply_policy()                                        # routing ticks do not silently remove it
    assert {"provider": "nous", "model": "h4"} in hermes.cfg["fallback_providers"]
    engine.set_private(False)
    chain = hermes.cfg["fallback_providers"]
    assert chain.count({"provider": "nous", "model": "h4"}) == 1 and chain.count(CLOUD) == 1


@respx.mock
def test_a_primary_changed_outside_pauses_and_is_reported_not_in_force(hermes):  # noqa: F811
    boxes()
    engine.set_private(True)
    hermes.cfg["model"] = {"provider": "openai-codex", "default": "gpt-5.5"}        # the user switches to cloud
    d = engine.apply_policy()
    assert store.load_state().get("paused") and hermes.cfg["model"]["provider"] == "openai-codex"   # respected
    st = engine.private_status()
    assert not st["in_force"] and any(p["what"] == "primary" for p in st["problems"])
    assert "paused" in d["warning"]
    engine.set_private(True)                                     # turning it on again takes routing back
    _no_cloud_anywhere(hermes.cfg)


@respx.mock
def test_no_switch_back_setting_never_keeps_cloud_in_private_mode(hermes):  # noqa: F811
    store.write_setting("failback_enabled", False)
    boxes(gx=False, s2=False)
    engine.apply_policy(unpin=True)
    assert hermes.cfg["model"]["provider"] == "openrouter"       # failed over to cloud before private mode
    boxes()
    engine.set_private(True)
    _no_cloud_anywhere(hermes.cfg)


def test_cannot_turn_on_without_an_enabled_box(hermes):  # noqa: F811
    for n in list(store.fleet().nodes):
        store.fleet().set_enabled(n["id"], False)
    assert "not turned on" in engine.set_private(True)
    assert not store.read_settings().get("private_only")
