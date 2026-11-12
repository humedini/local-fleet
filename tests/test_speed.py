"""Routing uses a box's best recent speed, so a bench taken while something else used the GPU
(ComfyUI on a DGX Spark, say) does not make the box look slow, and old figures stop counting."""
from datetime import datetime, timedelta, timezone

from local_fleet import health
from local_fleet.fleet import Fleet, routing_speed
from local_fleet.render import node_line


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def reading(tps, model="qwen", days=0.0):
    return {"tps": tps, "model": model, "at": ago(days)}


def fleet(*nodes):
    f = Fleet.__new__(Fleet)
    f.nodes = list(nodes)
    return f


def test_a_busy_reading_is_flagged_and_routing_keeps_the_best():
    n = {"id": "a", "name": "gx10", "kind": "ollama", "base_url": "http://gx:11434/v1"}
    f = fleet(n)
    f._record_perf({"a": reading(102.3)})
    busy = reading(15.3)
    f._record_perf({"a": busy})
    assert busy["below_best"] == 102.3 and n["perf"]["tps"] == 15.3
    assert routing_speed(n, "qwen") == 102.3
    assert "15.3t/s(best 102.3)" in node_line(n)


def test_a_faster_reading_raises_the_best_and_a_slightly_slower_one_is_not_flagged():
    n = {"id": "a", "name": "gx10"}
    f = fleet(n)
    f._record_perf({"a": reading(15.3)})       # first ever bench was taken while busy
    f._record_perf({"a": reading(102.3)})
    assert routing_speed(n, "qwen") == 102.3
    ok = reading(90.0)
    f._record_perf({"a": ok})
    assert "below_best" not in ok and routing_speed(n, "qwen") == 102.3


def test_best_is_kept_per_model():
    n = {"id": "a", "name": "gx10"}
    f = fleet(n)
    f._record_perf({"a": reading(100.0)})
    f._record_perf({"a": reading(300.0, model="tiny")})
    assert routing_speed(n, "qwen") == 100.0 and routing_speed(n, "tiny") == 300.0
    assert routing_speed(n, "") is None and routing_speed(n, "other") is None


def test_figures_older_than_a_week_stop_counting():
    n = {"id": "a", "name": "gx10", "perf": reading(100.0, days=8), "perf_best": {"qwen": reading(100.0, days=8)}}
    assert routing_speed(n, "qwen") is None
    fleet(n)._record_perf({"a": reading(40.0)})
    assert routing_speed(n, "qwen") == 40.0 and "below_best" not in n["perf"]


def test_boxes_benched_before_best_speeds_were_kept_still_count():
    assert routing_speed({"perf": {"tps": 90.0, "model": "qwen"}}, "qwen") == 90.0


def test_score_uses_the_best_not_the_busy_reading():
    snap = {"status": "ok", "load_proxy": 0.0, "models": ["qwen"]}
    gx = {"id": "a", "name": "gx10", "perf": {**reading(15.3), "below_best": 102.3},
          "perf_best": {"qwen": reading(102.3)}}
    z13 = {"id": "b", "name": "z13", "perf": reading(70.0)}
    assert health.pick_freest([z13, gx], {"a": snap, "b": snap}, want="qwen")["name"] == "gx10"
