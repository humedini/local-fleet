"""Handover v4 pre-deadline cut: rehearsal packs, incident card, savings receipt, the refusal toast
data and the guided demo's step order."""
import json
import re
import time
from pathlib import Path

import httpx
import respx

from local_fleet import engine, events, packs, reports, store, traffic
from test_engine import boxes, hermes  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


@respx.mock
def test_packs_tell_the_whole_story_and_clean_up_only_their_own(hermes):  # noqa: F811
    boxes()
    engine.apply_policy()                                     # routed to gx10
    s2 = store.fleet().get("spark2")["id"]
    engine.exclude(s2, "maintenance")                         # yours: must survive the packs' cleanup
    d = packs.run("local-a-down")
    assert "gx10 rehearsed out" in d["note"] and d["target"]["kind"] == "cloud"   # spark2 is in maintenance
    boxes()
    store.fleet().add("third", "http://t3:11434/v1")
    respx.get("http://t3:11434/v1/models").respond(json={"data": [{"id": "qwen"}]})
    respx.get("http://t3:11434/api/ps").respond(json={"models": []})
    d = packs.run("force-cloud-hop")
    assert d["target"]["kind"] == "cloud" and "Hermes on cloud" in d["note"]
    assert hermes.cfg["model"]["provider"] == "openrouter"
    d = packs.run("recover-drift")
    assert "2 rehearsal(s) ended" in d["note"] and "drift check: none" in d["note"]
    ex = store.load_state().get("exclusions") or {}
    assert list(ex) == [s2] and ex[s2]["kind"] == "maintenance"
    assert hermes.cfg["model"]["provider"] == "custom"        # recovered onto a box
    marks = [e["text"] for e in events.load() if e["kind"] == "pack"]
    assert any(m.startswith("Local A down: start") for m in marks) and any(m.startswith("Recover + drift: 2") for m in marks)
    assert all(e.get("pack") for e in events.load() if e["kind"] == "rehearsal" and "simulated outage" in e["text"])


@respx.mock
def test_packs_never_warm_or_hold_a_model_on_the_stand_in_box(hermes):  # noqa: F811
    store.write_setting("keep_loaded", True)
    boxes()
    engine.apply_policy()
    gen = respx.post("http://s2:11434/api/generate").respond(json={"done": True})
    packs.run("local-a-down")                                 # moves to spark2 while a rehearsal runs
    assert hermes.cfg["model"]["base_url"] == "http://s2:11434/v1" and not gen.called
    engine.apply_policy()                                     # a watch tick during the rehearsal: still no load
    assert not gen.called
    packs.end()


@respx.mock
def test_end_with_nothing_to_end_and_unknown_pack(hermes):  # noqa: F811
    boxes()
    assert packs.end()["ended"] == 0
    try:
        packs.run("nope")
        raise AssertionError
    except ValueError:
        pass


@respx.mock
def test_incident_card_is_scrubbed_and_separates_configured_from_served(hermes):  # noqa: F811
    store.fleet().add("lab", "http://10.0.0.21:11434/v1")
    boxes()
    respx.get("http://10.0.0.21:11434/v1/models").respond(json={"data": [{"id": "qwen"}]})
    respx.get("http://10.0.0.21:11434/api/ps").respond(json={"models": [{"name": "gemma"}, {"name": "x"}]})  # busier than gx10
    engine.apply_policy()
    respx.get("http://10.0.0.21:11434/v1/models").mock(side_effect=httpx.ConnectError("refused by http://10.0.0.21:11434 (lab.lan)"))
    engine.probe()
    store.write_setting("hide_addresses", False)               # the card is scrubbed whatever the setting
    card = reports.incident_card(24)
    for secret in ("10.0.0.21", "lab.lan", "http://", "sk-"):
        assert secret not in card, secret
    assert "Real outages:** 1" in card and "nothing here proves what answered" in card
    assert "Configured route:** gx10" in card
    traffic.record(True, base_url="http://gx:11434/v1", model="qwen", usage={"prompt_tokens": 10, "completion_tokens": 40})
    assert "Served (from Hermes's per-call hooks):** gx10" in reports.incident_card(24)


def test_incident_card_empty_state(hermes):  # noqa: F811
    assert "Nothing recorded" in reports.incident_card(1)


@respx.mock
def test_savings_receipt_matches_the_page_and_says_unavailable_without_a_price(hermes):  # noqa: F811
    boxes()
    traffic.record(True, base_url="http://gx:11434/v1", model="qwen", usage={"prompt_tokens": 1_000_000, "completion_tokens": 100_000})
    md, data = reports.savings_receipt("week")
    assert "unavailable" in md and data["saved"] is None
    store.write_setting("price_in_per_m", 3.0)
    store.write_setting("price_out_per_m", 15.0)
    store.write_setting("price_model", "x/y")
    md, data = reports.savings_receipt("week")
    assert data["saved"] == engine.snapshot()["traffic"]["saved"] == 4.5
    assert "(estimated)" in md and "not profit" in md and "x/y" in md
    md_today, _ = reports.savings_receipt("today")
    assert "today" in md_today


@respx.mock
def test_refusal_names_the_cloud_it_held_back_only_when_one_exists(hermes):  # noqa: F811
    boxes()
    engine.set_private(True)
    boxes(gx=False, s2=False)
    d = engine.apply_policy()
    assert d["avoided_cloud"] == "openrouter/anthropic/claude-sonnet-4"
    assert any(e["kind"] == "refused" and e.get("avoided") for e in events.load())
    boxes()
    assert "avoided_cloud" not in engine.apply_policy()          # an ordinary local pick claims nothing
    store.write_setting("cloud_model", "")
    boxes(gx=False, s2=False)
    assert engine.apply_policy()["avoided_cloud"] is None        # no cloud alternative, nothing avoided


def test_guided_demo_steps_follow_the_handover_order():
    js = (ROOT / "desktop" / "plugin.js").read_text()
    block = js[js.index("const DEMO_STEPS"):js.index("]", js.index("const DEMO_STEPS"))]
    ids = re.findall(r"id: '([a-z-]+)'", block)
    assert ids == ["why", "rehearsal", "cloud", "recovery", "drift", "readiness", "savings", "doctor"]
    secs = [int(x) for x in re.findall(r"secs: (\d+)", block)]
    assert len(secs) == 8 and sum(secs) <= 80                  # leaves room for API calls inside 90 s
    assert "post('/pack', { end: true })" in js and "e.key === 'Escape') exitDemo()" in js   # Exit and Esc clear the packs' rehearsals
