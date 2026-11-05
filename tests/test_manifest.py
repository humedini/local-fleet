"""plugin.yaml declares exactly what register() registers (the catalog's declared-tools/hooks rule)."""
from pathlib import Path

import yaml

import local_fleet

ROOT = Path(__file__).resolve().parent.parent


class Recorder:
    """A stand-in plugin context that records registrations."""
    def __init__(self):
        self.tools, self.hooks, self.commands, self.cli, self.skills, self.delegation = [], [], [], [], [], []

    def register_tool(self, name, **kw):
        self.tools.append(name)

    def register_hook(self, name, cb, **kw):
        self.hooks.append(name)

    def register_command(self, name, **kw):
        self.commands.append(name)

    def register_cli_command(self, name, **kw):
        self.cli.append(name)

    def register_skill(self, name, path, **kw):
        self.skills.append(name)
        assert Path(path).is_file()

    def register_delegation_provider(self, p):
        self.delegation.append(p)

    def set_config(self, *a):
        pass


def test_manifest_matches_registrations():
    m = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    ctx = Recorder()
    local_fleet.register(ctx)
    assert m["name"] == "local-fleet" and m["manifest_version"] == 2
    assert sorted(m["provides_tools"]) == sorted(ctx.tools)
    assert sorted(m["provides_hooks"]) == sorted(set(ctx.hooks))
    assert ctx.commands == ["fleet"] and ctx.cli == ["fleet"] and ctx.skills == ["local-fleet"]
    for key, spec in m["config_schema"].items():
        assert spec["type"] in ("str", "int", "float", "bool", "list"), key


def test_every_setting_has_a_schema_entry():
    from local_fleet.constants import DEFAULTS
    schema = yaml.safe_load((ROOT / "plugin.yaml").read_text())["config_schema"]
    assert set(DEFAULTS) == set(schema), set(DEFAULTS) ^ set(schema)


def test_catalog_entry_matches_the_manifest():
    m = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    c = yaml.safe_load((ROOT / "catalog" / "local-fleet.yaml").read_text())
    assert c["name"] == m["name"] and c["version"] == m["version"]
    assert sorted(c["capabilities"]["provides_tools"]) == sorted(m["provides_tools"])
    assert sorted(c["capabilities"]["provides_hooks"]) == sorted(m["provides_hooks"])
    assert c["requires_hermes"] == m["requires_hermes"]
