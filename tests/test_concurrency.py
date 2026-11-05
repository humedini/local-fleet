"""Several Local Fleet processes (gateway, Desktop backend, watch, CLI) share one profile's files."""
import threading

from local_fleet.fleet import Fleet


def test_stale_health_update_keeps_a_rename_and_never_resurrects(tmp_path):
    a = Fleet(tmp_path)
    a.add("one", "http://h1:1/v1")
    a.add("two", "http://h2:1/v1")
    ids = {n["name"]: n["id"] for n in a.nodes}
    stale = Fleet(tmp_path)                       # e.g. a watch tick that loaded the list earlier
    Fleet(tmp_path).update("one", title="Renamed")
    Fleet(tmp_path).remove("two")
    snap = {"checked_at": "2026-11-05T00:00:00+00:00", "status": "ok", "models": ["m"]}
    stale.record_health({ids["one"]: snap, ids["two"]: snap})
    now = Fleet(tmp_path).nodes
    assert [n["name"] for n in now] == ["one"] and now[0]["title"] == "Renamed"
    assert now[0]["last_health"]["status"] == "ok"


def test_threads_adding_at_once_lose_nothing(tmp_path):
    def add(i):
        Fleet(tmp_path).add(f"n{i}", f"http://h{i}:1/v1")
    ts = [threading.Thread(target=add, args=(i,)) for i in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(Fleet(tmp_path).nodes) == 16


CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
import conftest  # loads the plugin package as local_fleet
from local_fleet.fleet import Fleet
for i in range(int(sys.argv[3]), int(sys.argv[3]) + 8):
    Fleet(sys.argv[2]).add(f"p{i}", f"http://p{i}:1/v1")
"""


def test_processes_adding_at_once_lose_nothing(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    here = str(Path(__file__).resolve().parent)
    ps = [subprocess.Popen([sys.executable, "-c", CHILD, here, str(tmp_path), str(k * 8)]) for k in range(3)]
    assert all(p.wait(60) == 0 for p in ps)
    assert len(Fleet(tmp_path).nodes) == 24
