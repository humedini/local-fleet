import json
import shutil
from pathlib import Path

import pytest

from local_fleet.fleet import Fleet, FleetError, normalize_url, public_node

FIXTURE = Path(__file__).parent / "fixtures" / "fleet.json"


def test_add_list_remove_round_trip(tmp_path):
    f = Fleet(tmp_path)
    node = f.add("gx10", "http://192.168.1.50:11434/v1/", "ollama", labels=["lan", "lan", " gb10 "])
    assert node["base_url"] == "http://192.168.1.50:11434/v1"
    assert node["labels"] == ["gb10", "lan"]
    again = Fleet(tmp_path)
    assert [n["name"] for n in again.nodes] == ["gx10"]
    again.remove("GX10")
    assert Fleet(tmp_path).nodes == []


@pytest.mark.parametrize("name,url", [
    ("GX10", "http://10.0.0.9:11434/v1"),          # same name, other case
    ("other", "http://192.168.1.50:11434/v1/"),     # same URL, trailing slash
])
def test_duplicates_rejected(tmp_path, name, url):
    f = Fleet(tmp_path)
    f.add("gx10", "http://192.168.1.50:11434/v1")
    with pytest.raises(FleetError):
        f.add(name, url)


@pytest.mark.parametrize("url", ["ftp://x/v1", "192.168.1.50:11434", "http://user:pw@h/v1", "http://h/v1?k=1", ""])
def test_bad_urls_rejected(url):
    with pytest.raises(FleetError):
        normalize_url(url)


def test_bad_kind_and_key_value_rejected(tmp_path):
    f = Fleet(tmp_path)
    with pytest.raises(FleetError):
        f.add("a", "http://h:1/v1", kind="comfyui")
    with pytest.raises(FleetError):
        f.add("b", "http://h:2/v1", api_key_env="sk-live-abc123")  # a key, not a variable name


def test_unknown_node_is_a_fleet_error(tmp_path):
    with pytest.raises(FleetError):
        Fleet(tmp_path).remove("nope")


def test_fixture_loads_and_finds_by_id_or_name(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "fleet.json")
    f = Fleet(tmp_path)
    assert f.get("d4e5f6")["name"] == "spark2"
    assert f.get("Spark2")["id"] == "d4e5f6"


def test_disable_keeps_node_but_drops_it_from_enabled(tmp_path):
    f = Fleet(tmp_path)
    f.add("a", "http://h:1/v1")
    f.set_enabled("a", False)
    assert f.enabled() == [] and len(Fleet(tmp_path).nodes) == 1


def test_public_node_hides_the_env_var_name_and_no_key_is_ever_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_KEY", "secret-value")
    f = Fleet(tmp_path)
    node = f.add("a", "http://h:1/v1", api_key_env="SPARK_KEY")
    assert "secret-value" not in (tmp_path / "fleet.json").read_text()
    pub = public_node(node)
    assert "api_key_env" not in pub and pub["needs_key"] is True
    json.dumps(pub)
