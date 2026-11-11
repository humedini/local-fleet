"""Catalog review fixes (hermes-agent PR 152948): no API key follows the primary to a box, no key is
copied into plugin data, pulls need approval and come only from Ollama's library, and the background
refresh runs in the session's profile context."""
import contextvars
import json

import respx

import local_fleet
from local_fleet import aux, config_write, engine, store, tools
from test_engine import boxes, hermes  # noqa: F401  (fixture)

SECRET = "sk-live-not-for-boxes"
CLOUD_KEYED = {"provider": "custom", "model": "big", "base_url": "https://api.cloud.example/v1",
               "api_key": "${CLOUD_KEY}"}


def _everywhere(hermes):  # noqa: F811
    """Everything Local Fleet keeps (its state and settings files) plus Hermes's config, as text."""
    data = json.dumps(store.load_state()) + json.dumps(store.read_settings())
    return data, json.dumps(hermes.cfg)


@respx.mock
def test_primary_with_an_inline_key_is_never_moved(hermes):  # noqa: F811
    boxes()
    hermes.cfg["model"] = {"provider": "custom", "default": "m", "base_url": "https://vendor.example/v1",
                           "api_key": SECRET}
    before = json.dumps(hermes.cfg["model"])
    d = engine.apply_policy()
    assert not d["applied"] and "model.api_key" in d["warning"]
    assert json.dumps(hermes.cfg["model"]) == before
    assert SECRET not in _everywhere(hermes)[0]


@respx.mock
def test_env_reference_and_api_alias_count_as_inline_keys_too(hermes):  # noqa: F811
    boxes()
    hermes.env["VENDOR_KEY"] = SECRET
    hermes.cfg["model"] = {"provider": "custom", "default": "m", "base_url": "https://vendor.example/v1",
                           "api": "${VENDOR_KEY}"}
    d = engine.apply_policy()
    assert not d["applied"] and "model.api" in d["warning"]
    assert hermes.cfg["model"]["base_url"] == "https://vendor.example/v1"


@respx.mock
def test_api_key_env_pointer_is_cleared_on_a_box_and_restored(hermes):  # noqa: F811
    boxes()
    hermes.cfg["model"] = {"provider": "azure-anthropic", "default": "m", "api_key_env": "AZURE_KEY"}
    assert engine.apply_policy()["applied"]
    assert "api_key_env" not in hermes.cfg["model"]
    engine.restore()
    assert hermes.cfg["model"]["api_key_env"] == "AZURE_KEY"


@respx.mock
def test_private_mode_keeps_env_references_as_references(hermes):  # noqa: F811
    boxes()
    hermes.env["CLOUD_KEY"] = SECRET
    hermes.cfg["fallback_providers"] = [dict(CLOUD_KEYED)]
    engine.set_private(True)
    assert CLOUD_KEYED not in hermes.cfg["fallback_providers"]
    data, config = _everywhere(hermes)
    assert SECRET not in data and "${CLOUD_KEY}" in data
    engine.set_private(False)
    assert CLOUD_KEYED in hermes.cfg["fallback_providers"]  # back as written, ${CLOUD_KEY} intact
    assert SECRET not in json.dumps(hermes.cfg) and SECRET not in _everywhere(hermes)[0]


@respx.mock
def test_private_mode_leaves_a_literal_keyed_entry_and_reports_not_in_force(hermes):  # noqa: F811
    boxes()
    entry = {**CLOUD_KEYED, "api_key": SECRET}
    hermes.cfg["fallback_providers"] = [entry]
    out = engine.set_private(True)
    assert "NOT fully in force" in out and "custom/big" in out
    assert entry in hermes.cfg["fallback_providers"]
    assert SECRET not in _everywhere(hermes)[0]
    assert not engine.private_status()["in_force"]


@respx.mock
def test_older_plugin_data_holding_a_key_is_put_back_and_dropped(hermes):  # noqa: F811
    boxes()
    store.update_state(private_removed=[{**CLOUD_KEYED, "api_key": SECRET}])
    engine.set_private(True)
    assert SECRET not in _everywhere(hermes)[0]
    assert any(e.get("api_key") == SECRET for e in hermes.cfg["fallback_providers"])


def test_side_task_snapshot_keeps_env_references(hermes):  # noqa: F811
    hermes.env["CLOUD_KEY"] = SECRET
    hermes.cfg["auxiliary"] = {"compression": {"provider": "auto", "fallback_chain": [dict(CLOUD_KEYED)]}}
    before = aux.apply(["compression"], {"provider": "ollama", "model": "q", "base_url": "http://gx:11434/v1"}, None)
    assert before["compression"]["fallback_chain"][0]["api_key"] == "${CLOUD_KEY}"
    aux.apply(["compression"], None, before)
    assert hermes.cfg["auxiliary"]["compression"]["fallback_chain"][0]["api_key"] == "${CLOUD_KEY}"


def test_secret_fields_names_paths_never_values():
    block = {"provider": "x", "api_key": SECRET, "fallback_chain": [{"token": "${T}"}, {"password": "p"}]}
    assert config_write.secret_fields(block) == ["api_key", "fallback_chain[1].password"]
    assert config_write.secret_fields(block, literal_only=False) == [
        "api_key", "fallback_chain[0].token", "fallback_chain[1].password"]


def test_pull_tags_come_only_from_the_ollama_library():
    for ok in ("qwen3:14b", "qwen3.6:35b-a3b", "library/llama3.1:8b", "user/model:q4"):
        assert tools.valid_tag(ok), ok
    for bad in ("registry.evil.example/x/model:latest", "hf.co/user/gguf", "host:5000/model",
                "localhost:11434/m", "bad tag; rm -rf", ""):
        assert not tools.valid_tag(bad), bad


def test_registry_pull_is_refused_before_any_request(hermes):  # noqa: F811
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://gx:11434/api/pull")
        out = json.loads(tools.fleet_pull_model({"node": "gx10", "model": "evil.example/x/y:1"}))
        assert not out["ok"] and "registry" in out["error"] and not route.called


def test_every_pull_goes_through_hermes_approval():
    d = tools.pull_approval(tool_name="fleet_pull_model", args={"node": "gx10", "model": "qwen3:14b"})
    assert d == {"action": "approve", "message": "Local Fleet: pull qwen3:14b onto gx10"}
    assert tools.pull_approval(tool_name="fleet_status", args={}) is None


def test_hook_is_registered_and_declared():
    import pathlib
    hooks = []

    class Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: hooks.append((a, k)) if name == "register_hook" else None

    local_fleet.register(Ctx())
    assert any(a[:2] == ("pre_tool_call", tools.pull_approval) for a, _ in hooks)
    manifest = (pathlib.Path(local_fleet.__file__).parent / "plugin.yaml").read_text()
    assert "  - pre_tool_call" in manifest


def test_session_refresh_runs_in_the_callers_profile_context(hermes, monkeypatch):  # noqa: F811
    profile = contextvars.ContextVar("profile", default="launch")
    seen = []
    import threading
    done = threading.Event()

    def fake_apply(**kw):
        seen.append(profile.get())
        done.set()

    monkeypatch.setattr(engine, "apply_policy", fake_apply)
    profile.set("work")
    local_fleet._refresh_on_session_start()
    assert done.wait(5) and seen == ["work"]
