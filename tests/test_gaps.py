"""Handover v3 gaps: side-task drift on every owned field, Doctor's plain-HTTP and watch checks,
one readiness threshold everywhere, and an explicit savings baseline."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
import respx

from local_fleet import cli, doctor, engine, store, traffic
from test_engine import boxes, hermes  # noqa: F401  (fixture)


@pytest.mark.parametrize("field,value", [
    ("provider", "openrouter"), ("model", "other"), ("base_url", "http://elsewhere:8000/v1"),
    ("fallback_chain", [{"provider": "nous", "model": "h4"}]), ("api_key", "sk-ADDED-1"), ("key_env", "SOME_KEY"),
])
@respx.mock
def test_side_task_drift_on_each_owned_field_pauses_and_never_fights(hermes, field, value):  # noqa: F811
    store.write_setting("aux_tasks", ["compression"])
    boxes()
    engine.apply_policy()
    hermes.cfg["auxiliary"]["compression"][field] = copy.deepcopy(value)   # another writer
    edited = copy.deepcopy(hermes.cfg["auxiliary"]["compression"])
    d = engine.apply_policy()
    assert "paused" in (d.get("aux") or "")
    assert any(x["what"] == "side tasks" for x in engine.drift())
    boxes(gx=False)                                              # routing moves; side tasks must not follow
    engine.apply_policy()
    assert hermes.cfg["auxiliary"]["compression"] == edited      # left exactly as the other writer set it
    if field == "api_key":
        for f in store.data_dir().rglob("*"):
            if f.is_file():
                assert "sk-ADDED-1" not in f.read_text(errors="ignore")
    engine.relinquish()                                          # stop managing: config untouched
    assert hermes.cfg["auxiliary"]["compression"] == edited and engine.drift() == []


@respx.mock
def test_side_task_reapply_takes_back_after_drift(hermes):  # noqa: F811
    store.write_setting("aux_tasks", ["compression"])
    boxes()
    engine.apply_policy()
    hermes.cfg["auxiliary"]["compression"]["fallback_chain"] = []
    engine.apply_policy()
    engine.reapply()
    assert hermes.cfg["auxiliary"]["compression"]["fallback_chain"] == [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}]
    assert engine.drift() == []


@respx.mock
def test_doctor_warns_on_plain_http_to_a_public_address(hermes):  # noqa: F811
    store.fleet().add("rented", "http://93.184.215.14:11434/v1")
    boxes()
    respx.get("http://93.184.215.14:11434/v1/models").respond(json={"data": [{"id": "qwen"}]})
    respx.get("http://93.184.215.14:11434/api/ps").respond(json={"models": []})
    items = doctor.checks()
    http = [c for c in items if c["id"].startswith("http:")]
    assert len(http) == 1 and http[0]["level"] == "warn" and "rented" in http[0]["title"]
    for url in ("http://192.168.1.5:11434/v1", "http://100.80.1.2:11434/v1", "http://box.tail1.ts.net/v1",
                "http://gx10:11434/v1", "http://localhost:11434/v1", "http://spark.lan:11434/v1"):
        assert doctor.is_private_address(url), url
    assert not doctor.is_private_address("http://example.com:11434/v1")


@respx.mock
def test_doctor_probe_does_not_count_as_a_running_watch(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()                                        # routed, and probed just now
    w = next(c for c in doctor.checks() if c["id"] == "watch")
    assert w["level"] == "info" and "Nothing is keeping routing current" in w["title"]
    w = next(c for c in doctor.checks() if c["id"] == "watch")   # still: the doctor's own probe changed nothing
    assert w["level"] == "info"
    store.update_state(watch_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), watch_interval_s=30)
    assert next(c for c in doctor.checks() if c["id"] == "watch")["level"] == "ok"
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
    store.update_state(watch_at=old)
    w = next(c for c in doctor.checks() if c["id"] == "watch")
    assert w["level"] == "info" and "has not ticked" in w["title"]


@respx.mock
def test_watch_records_its_heartbeat(hermes):  # noqa: F811
    boxes()
    import argparse
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    cli.main(p.parse_args(["watch", "--once", "--interval", "15"]))
    st = store.load_state()
    assert st["watch_at"] and st["watch_interval_s"] == 15


def test_snapshot_exports_the_configured_readiness_threshold(hermes):  # noqa: F811
    store.write_setting("min_context", 65536)
    s = engine.snapshot()
    assert s["min_context"] == 65536 and s["probe_interval_s"] > 0


def test_savings_baseline_is_recorded_not_guessed(hermes, capsys):  # noqa: F811
    t = traffic.summarize([{"t": 1, "n": "x", "in": 1000, "out": 10}], (3.0, 15.0))
    assert t["breakdown"]["baseline"]["model"] is None and "not recorded" in t["breakdown"]["baseline"]["source"]
    import argparse
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    cli.main(p.parse_args(["price", "3", "15", "--currency", "GBP", "--model", "anthropic/claude-sonnet-4.5"]))
    assert "claude-sonnet-4.5" in capsys.readouterr().out
    assert store.read_settings()["price_model"] == "anthropic/claude-sonnet-4.5"
    assert engine.snapshot()["traffic"]["breakdown"]["baseline"]["model"] == "anthropic/claude-sonnet-4.5"
    cli.main(p.parse_args(["price", "1", "2"]))                  # no --model: the cloud backup, said so
    assert store.read_settings()["price_model"] == "openrouter/anthropic/claude-sonnet-4"
