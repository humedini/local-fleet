import httpx
import respx

from hermes_spark.health import origin, pick_freest, probe_all, score

GX = {"id": "a", "name": "gx10", "base_url": "http://gx:11434/v1", "kind": "ollama", "labels": ["lan"]}
S2 = {"id": "b", "name": "spark2", "base_url": "http://s2:11434/v1", "kind": "ollama", "labels": []}
VL = {"id": "c", "name": "vl", "base_url": "http://vl:8000/v1", "kind": "vllm", "labels": []}
OA = {"id": "d", "name": "oa", "base_url": "https://oa.example/v1", "kind": "openai-compatible", "labels": []}


def models(*ids):
    return {"object": "list", "data": [{"id": i} for i in ids]}


def ps(*names, vram=10_000_000_000):
    return {"models": [{"name": n, "size_vram": vram} for n in names]}


def test_origin_strips_v1():
    assert origin("http://h:11434/v1") == "http://h:11434"
    assert origin("http://h/proxy/v1/") == "http://h/proxy"
    assert origin("http://h:4000") == "http://h:4000"


@respx.mock
def test_ollama_ok_with_load_from_other_resident_models():
    respx.get("http://gx:11434/v1/models").respond(json=models("qwen", "gemma"))
    respx.get("http://gx:11434/api/ps").respond(json=ps("gemma", "qwen"))
    snap = probe_all([GX], want="qwen")["a"]
    assert snap["status"] == "ok"
    assert snap["load_proxy"] == 0.25          # gemma counts, the wanted qwen does not
    assert snap["resident"] == ["gemma", "qwen"]
    assert snap["models"] == ["qwen", "gemma"]


@respx.mock
def test_ollama_capacity_gives_free_memory():
    node = dict(GX, capacity_gb=100)
    respx.get("http://gx:11434/v1/models").respond(json=models("qwen"))
    respx.get("http://gx:11434/api/ps").respond(json=ps("gemma", vram=25_000_000_000))
    snap = probe_all([node], want="qwen")["a"]
    assert snap["load_proxy"] == 0.25 and snap["free_vram_approx"] == 75_000_000_000


@respx.mock
def test_down_on_timeout_and_http_error_never_raises():
    respx.get("http://gx:11434/v1/models").mock(side_effect=httpx.ConnectTimeout("t"))
    respx.get("http://s2:11434/v1/models").respond(status_code=503)
    out = probe_all([GX, S2])
    assert out["a"]["status"] == "down" and out["a"]["detail"] == "timeout"
    assert out["b"]["status"] == "down" and "503" in out["b"]["detail"]


@respx.mock
def test_degraded_when_load_endpoint_fails():
    respx.get("http://gx:11434/v1/models").respond(json=models("qwen"))
    respx.get("http://gx:11434/api/ps").respond(status_code=404)
    snap = probe_all([GX])["a"]
    assert snap["status"] == "degraded" and snap["load_proxy"] is None


@respx.mock
def test_vllm_cache_usage_and_openai_latency_only():
    respx.get("http://vl:8000/v1/models").respond(json=models("m"))
    respx.get("http://vl:8000/metrics").respond(
        text='# HELP x\nvllm:num_requests_running{model_name="m"} 3.0\nvllm:gpu_cache_usage_perc{model_name="m"} 0.4\n')
    respx.get("https://oa.example/v1/models").respond(json=models("m"))
    out = probe_all([VL, OA])
    assert out["c"]["load_proxy"] == 0.4
    assert out["d"]["status"] == "ok" and out["d"]["load_proxy"] is None


@respx.mock
def test_key_sent_only_to_its_own_node(monkeypatch):
    monkeypatch.setenv("VL_KEY", "k1")
    vl = dict(VL, api_key_env="VL_KEY")
    a = respx.get("http://vl:8000/v1/models").respond(json=models("m"))
    respx.get("http://vl:8000/metrics").respond(text="vllm:num_requests_running 0\n")
    b = respx.get("http://gx:11434/v1/models").respond(json=models("m"))
    respx.get("http://gx:11434/api/ps").respond(json=ps())
    probe_all([vl, GX])
    assert a.calls.last.request.headers["authorization"] == "Bearer k1"
    assert "authorization" not in b.calls.last.request.headers


def snap(status="ok", load=0.0, lat=10, models=("qwen",), free=None):
    return {"status": status, "load_proxy": load, "latency_ms": lat, "models": list(models),
            "free_vram_approx": free}


def test_freest_prefers_lower_load_then_latency_then_name():
    assert pick_freest([GX, S2], {"a": snap(load=0.5), "b": snap(load=0.0)})["name"] == "spark2"
    assert pick_freest([GX, S2], {"a": snap(lat=5), "b": snap(lat=50)})["name"] == "gx10"
    assert pick_freest([S2, GX], {"a": snap(), "b": snap()})["name"] == "gx10"   # stable tie-break


def test_freest_skips_down_and_nodes_without_the_wanted_model():
    res = {"a": snap(status="down"), "b": snap(models=("gemma",))}
    assert pick_freest([GX, S2], res) ["name"] == "spark2"
    assert pick_freest([GX, S2], res, want="qwen") is None


def test_unknown_load_ranks_between_idle_and_busy():
    assert score(GX, snap(load=None))[1] == 0.5


def test_label_preference_breaks_load_ties():
    res = {"a": snap(lat=50), "b": snap(lat=5)}
    assert pick_freest([GX, S2], res, prefer_labels=["lan"])["name"] == "gx10"
