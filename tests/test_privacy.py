"""With hide_addresses on, no box address escapes any output: Desktop REST (responses and errors),
the decision inspector, the flight recorder (stored file included), CLI text and JSON, the agent
tools and the snapshot export. The fixtures use recognisable addresses inside raw probe errors."""
import json

import httpx
import pytest
import respx

from local_fleet import cli, engine, events, render, store, tools
from test_engine import boxes, hermes  # noqa: F401  (fixture)
from test_plugin_api import client  # noqa: F401  (fixture)

SECRETS = ("10.0.0.21", "spark-a.lan", "spark-a", "100.99.1.2", "http://")


def _clean(text: str) -> None:
    for s in SECRETS:
        assert s not in text, (s, text[:400])


def _fleet(up: bool):
    """gx10 and spark2 from the fixture, plus two boxes with telling addresses whose probe errors quote them."""
    boxes()
    for url in ("http://10.0.0.21:11434", "http://spark-a.lan:11434"):
        if up:
            respx.get(f"{url}/v1/models").respond(json={"data": [{"id": "qwen"}]})
            respx.get(f"{url}/api/ps").respond(json={"models": []})
        else:
            respx.get(f"{url}/v1/models").mock(side_effect=httpx.ConnectError(
                f"All connection attempts failed for {url}/v1/models via 100.99.1.2"))


@pytest.fixture
def private_boxes(hermes):  # noqa: F811
    f = store.fleet()
    f.add("lab", "http://10.0.0.21:11434/v1")
    f.add("attic", "http://spark-a.lan:11434/v1")
    store.write_setting("hide_addresses", True)
    return hermes


@respx.mock
def test_desktop_rest_never_returns_an_address(private_boxes, client):  # noqa: F811
    base = "/api/plugins/local-fleet"
    _fleet(up=True)
    client.post(f"{base}/probe")
    _fleet(up=False)                                             # the two go down: errors quote their URLs
    out = [client.get(f"{base}/status").text, client.post(f"{base}/why").text, client.post(f"{base}/probe").text,
           client.get(f"{base}/doctor").text, client.post(f"{base}/use", json={"node": "best"}).text,
           client.post(f"{base}/use", json={"node": "nope"}).text,
           client.post(f"{base}/private", json={"on": True}).text]
    for text in out:
        _clean(text)
    why = json.loads(out[1])
    lab = next(c for c in why["decision"]["candidates"] if c["name"] == "lab")
    assert not lab["eligible"] and "<address>" in lab["reason"]   # the reason survives, its address does not
    assert all("base_url" not in n for n in json.loads(out[0])["nodes"])


@respx.mock
def test_recorder_file_never_stores_an_address_even_with_privacy_off(private_boxes):  # noqa: F811
    store.write_setting("hide_addresses", False)
    _fleet(up=True)
    engine.probe()
    _fleet(up=False)
    engine.probe()
    downs = [e for e in events.load() if e["kind"] == "health"]
    assert {e["box"] for e in downs} >= {"lab", "attic"}
    _clean((store.data_dir() / events.FILE).read_text())


@respx.mock
def test_cli_text_json_tools_and_export_hide_addresses(private_boxes, capsys):  # noqa: F811
    _fleet(up=True)
    engine.probe()
    _fleet(up=False)
    engine.probe()
    render.configure(True, store.fleet().nodes)
    try:
        nodes = store.fleet().nodes
        _clean(render.nodes_table(nodes))
        _clean(render.why_text(engine.apply_policy(dry_run=True)))
        _clean(render.events_text(events.timeline(40)))
    finally:
        render.configure(False)
    for argv in (["status"], ["status", "--json"], ["list", "--json"], ["why"], ["doctor"], ["snapshot"], ["events"]):
        ns = _parse(argv)
        try:
            cli.main(ns)
        except SystemExit:
            pass
        _clean(capsys.readouterr().out)
    _clean(tools.fleet_status({}))
    _clean(tools.fleet_list_nodes({}))
    _clean(json.dumps(cli.snapshot_view()))


def test_box_names_that_are_also_hosts_stay_visible():
    nodes = [{"name": "gx10", "base_url": "http://gx10:11434/v1"}, {"name": "lab", "base_url": "http://10.0.0.21:11434/v1"}]
    assert render.mask("gx10 down: connect to gx10:11434 failed (10.0.0.21)", render.hosts_of(nodes)) == \
        "gx10 down: connect to <address> failed (<address>)"
    assert render.mask("simulated outage (rehearsal) until 14:05 · qwen3:14b") == "simulated outage (rehearsal) until 14:05 · qwen3:14b"


def _parse(argv):
    import argparse
    p = argparse.ArgumentParser()
    cli.setup_argparse(p)
    return p.parse_args(argv)
