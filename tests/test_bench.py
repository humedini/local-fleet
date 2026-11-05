import json

import httpx
import respx

from local_fleet.bench import bench_node, pick_model

OL = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama"}
VL = {"id": "b", "name": "vl", "base_url": "http://vl:8000/v1", "kind": "vllm"}


def snap(models=("qwen", "gemma"), resident=("gemma",), load=0.0, status="ok"):
    return {"status": status, "models": list(models), "resident": list(resident), "load_proxy": load}


def test_never_cold_loads_an_ollama_model_unless_asked():
    assert pick_model(OL, snap(), "qwen", load=False) == ("gemma", "")      # wanted not in memory: use what is
    assert pick_model(OL, snap(resident=("qwen",)), "qwen", load=False) == ("qwen", "")
    assert pick_model(OL, snap(), "qwen", load=True) == ("qwen", "")
    assert pick_model(OL, snap(resident=()), "", load=False)[0] == ""
    assert pick_model(OL, snap(resident=("mxbai-embed-large",)), "", load=False)[0] == ""


@respx.mock
def test_ollama_speed_from_its_own_timings():
    route = respx.post("http://gx:11434/api/generate").respond(json={
        "eval_count": 64, "eval_duration": 2_000_000_000, "prompt_eval_count": 30,
        "prompt_eval_duration": 100_000_000, "load_duration": 5_000_000})
    r = bench_node(OL, snap(), "")
    assert r["tps"] == 32.0 and r["prompt_tps"] == 300.0 and r["model"] == "gemma"
    sent = json.loads(route.calls.last.request.content)
    assert sent["options"]["num_predict"] == 64 and sent["stream"] is False


@respx.mock
def test_openai_speed_from_the_stream():
    chunks = [{"choices": [{"delta": {"content": str(i)}}]} for i in range(11)]
    chunks.append({"choices": [], "usage": {"completion_tokens": 11}})
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    respx.post("http://vl:8000/v1/chat/completions").respond(text=body)
    r = bench_node(VL, snap(resident=()), "qwen")
    assert r["tokens"] == 11 and r["tps"] > 0 and r["model"] == "qwen" and "ttft_ms" in r


def test_skips_busy_and_unhealthy_boxes():
    assert bench_node(OL, snap(load=0.75), "")["skipped"] == "busy"
    assert bench_node(OL, snap(status="down"), "")["skipped"] == "not healthy"


@respx.mock
def test_errors_come_back_as_data():
    respx.post("http://gx:11434/api/generate").mock(side_effect=httpx.ConnectError("x"))
    assert "ConnectError" in bench_node(OL, snap(), "")["error"]


@respx.mock
def test_bench_keeps_the_models_remaining_idle_time():
    from datetime import datetime, timedelta, timezone
    route = respx.post("http://gx:11434/api/generate").respond(json={"eval_count": 10, "eval_duration": 1_000_000_000})
    at = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat().replace("+00:00", "Z")
    bench_node(OL, dict(snap(), expires={"gemma": at}), "")
    sent = json.loads(route.calls.last.request.content)["keep_alive"]
    assert sent.endswith("s") and 290 <= int(sent[:-1]) <= 300


def test_bench_uses_the_first_tier_the_box_has():
    s = snap(models=("small", "other"), resident=("other",))
    assert pick_model(OL, s, ["big", "small"], load=True) == ("small", "")
    assert pick_model(OL, s, ["big", "small"], load=False) == ("other", "")   # never cold-loads uninvited
