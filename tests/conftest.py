"""Load the plugin directory as the package `hermes_spark` so tests need no Hermes install."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent



def _load():
    if "hermes_spark" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        "hermes_spark", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_spark"] = mod
    spec.loader.exec_module(mod)


_load()

