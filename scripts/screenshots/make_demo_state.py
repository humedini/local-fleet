#!/usr/bin/env python3
"""Synthetic Local Fleet state for screenshots: every name, address, model, number and event here
is invented (10.0.0.x addresses, public model tags, made-up traffic). Nothing is read from a real
fleet. Writes demo-status.json next to this file in the shape GET /api/plugins/local-fleet/status
returns."""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)
NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
MAIN, FALLBACK = "gpt-oss:120b", "qwen3:14b"


def iso(minutes_ago=0.0):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def node(i, name, ip, vendor, os_name, models, resident, load, lat, free_gb, tps, labels, status="ok"):
    return {
        "id": f"d{i:05d}", "name": name, "base_url": f"http://{ip}:11434/v1", "kind": "ollama",
        "labels": labels, "enabled": True, "needs_key": False, "capacity_gb": 128 if vendor == "nvidia" else None,
        "vendor": vendor, "os": os_name, "platform": {"vendor": vendor, "os": os_name, "guessed": False},
        "models": models,
        "last_health": {"checked_at": iso(0.2), "status": status, "latency_ms": lat if status == "ok" else None,
                        "free_vram_approx": free_gb * 1e9 if free_gb else None, "load_proxy": load if status == "ok" else None,
                        "detail": "ok" if status == "ok" else "timeout", "models": models if status == "ok" else [],
                        "resident": resident},
        "perf": {"tps": tps, "tokens": 64, "prompt_tps": round(tps * 9.5, 1), "model": resident[0] if resident else MAIN,
                 "at": iso(6)} if tps else None,
    }


nodes = [
    node(1, "spark-a", "10.0.0.21", "nvidia", "linux", [MAIN, "qwen3:32b", "llama3.3:70b", "gemma3:27b", FALLBACK],
         [MAIN], 0.0, 4, 61, 41.8, ["lan", "gb10"]),
    node(2, "spark-b", "10.0.0.22", "nvidia", "linux", [MAIN, "qwen3:32b", "llama3.3:70b", FALLBACK],
         [MAIN, "llama3.3:70b"], 0.44, 5, 18, 39.6, ["lan", "gb10"]),
    node(3, "studio", "10.0.0.30", "apple", "macos", [MAIN, "qwen3:32b", "gemma3:27b", FALLBACK],
         [], 0.0, 9, None, 33.2, ["lan"]),
    node(4, "strix", "10.0.0.40", "amd", "linux", [FALLBACK, "qwen3:32b", "gemma3:27b"],
         [FALLBACK], 0.25, 7, None, 58.4, ["lan"]),
]
# Memory: total, what models may use, and what is loaded now (invented, plausible sizes).
MEM = {"spark-a": (128, 120, {MAIN: 65e9}), "spark-b": (128, 120, {MAIN: 65e9, "llama3.3:70b": 37e9}),
       "studio": (192, 160, {}), "strix": (128, 96, {FALLBACK: 10.4e9})}
for n in nodes:
    total, cap, sizes = MEM[n["name"]]
    n["memory_gb"], n["capacity_gb"] = total, cap
    h = n["last_health"]
    h["sizes"], h["used_bytes"], h["version"] = sizes, int(sum(sizes.values())), "0.13.4"
    h["free_vram_approx"] = int(cap * 1e9 - sum(sizes.values()))
nodes[2]["perf"]["model"] = MAIN
nodes[3]["perf"]["model"] = FALLBACK

series = {}
for k, n in enumerate(nodes):
    base = n["last_health"]["latency_ms"] or 6
    load = n["last_health"]["load_proxy"] or 0
    series[n["id"]] = [{"t": iso(30 - i), "lat": round(base + 2 * math.sin(i / 2 + k) + random.random() * 2, 1),
                        "load": max(0, min(1, load + 0.15 * math.sin(i / 3 + k))), "st": "ok"} for i in range(30)]

# Two Sparks linked over 200 GbE serve one big model behind the head node's vLLM endpoint.
BIG = "llama3.1:405b"
cluster = {
    "id": "d00009", "name": "spark-pair", "title": "Spark pair", "base_url": "http://10.0.0.21:8000/v1", "kind": "vllm",
    "labels": ["lan"], "enabled": True, "needs_key": False, "members": ["d00001", "d00002"], "link": "200 GbE",
    "vendor": "nvidia", "os": "linux", "platform": {"vendor": "nvidia", "os": "linux", "guessed": False},
    "models": [BIG],
    "last_health": {"checked_at": iso(0.2), "status": "ok", "latency_ms": 6, "free_vram_approx": None, "load_proxy": 0.35,
                    "detail": "ok", "models": [BIG], "resident": []},
    "perf": {"tps": 14.2, "tokens": 64, "prompt_tps": 212.0, "model": BIG, "at": iso(5)},
}
nodes[0]["title"] = "Spark A"
nodes[1]["title"] = "Spark B"
nodes[2]["title"] = "Mac Studio"
for m in nodes[:2]:  # the cluster's load reaches its members
    m["last_health"]["load_proxy"] = max(m["last_health"]["load_proxy"] or 0, 0.35)
nodes.insert(0, cluster)
series[cluster["id"]] = [{"t": iso(30 - i), "lat": round(6 + math.sin(i / 2), 1), "load": 0.3 + 0.1 * math.sin(i / 4), "st": "ok"} for i in range(30)]

state = {
    "mode": "auto", "label": "spark-pair",
    "primary": {"provider": "custom", "default": "llama3.1:405b", "base_url": "http://10.0.0.21:8000/v1", "api_mode": "chat_completions"},
    "local_model": BIG, "model_tiers": [BIG, MAIN, FALLBACK],
    "applied": {"kind": "local", "node_id": "d00009", "node_name": "spark-pair", "base_url": cluster["base_url"], "model": BIG},
    "down": False, "nodes": nodes, "healthy": 4,
    "last_decision": {"reason": "least busy box: spark-pair", "freest_node_id": "d00009", "at": iso(4)},
    "last_probe_at": iso(0.2), "series": series,
    "history": [
        {"at": iso(185), "reason": "least busy box: spark-b", "kind": "local", "node": "spark-b", "model": MAIN},
        {"at": iso(122), "reason": "no box available with gpt-oss:120b or qwen3:14b, using cloud", "kind": "cloud",
         "model": "anthropic/claude-sonnet-4", "via": "failover"},
        {"at": iso(117), "reason": "back on spark-a (it recovered)", "kind": "local", "node": "spark-a", "model": MAIN},
        {"at": iso(4), "reason": "back to your main model on spark-pair", "kind": "local", "node": "spark-pair", "model": "llama3.1:405b"},
    ],
    "fallback_chain": [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}],
    "traffic": {"boxes": {
        "d00009": {"calls": 188, "errors": 0, "in": 2_400_000, "out": 140_000, "live": 2, "tps": 12.9, "latency_s": 14.2},
        "d00001": {"calls": 412, "errors": 1, "in": 3_910_000, "out": 402_000, "live": 3, "tps": 38.2, "latency_s": 6.1},
        "d00002": {"calls": 236, "errors": 0, "in": 2_150_000, "out": 231_000, "live": 0, "tps": 35.7, "latency_s": 7.4},
        "d00003": {"calls": 97, "errors": 0, "in": 880_000, "out": 96_000, "live": 2, "tps": 29.9, "latency_s": 8.8},
        "d00004": {"calls": 58, "errors": 2, "in": 210_000, "out": 44_000, "live": 0, "tps": 51.0, "latency_s": 2.3}},
        "local_tokens": 7_923_000, "cloud_tokens": 1_120_000, "local_share": 0.876, "saved": 36.23, "calls": 870},
    "currency": "USD", "delegation_backend": "fleet",
    "aux": {"tasks": ["title_generation", "compression"], "node_id": "d00004", "node_name": "strix", "model": FALLBACK},
    "delegations": [{"at": iso(0.5), "label": "studio"}],
}
# The demo clock is fixed; the page compares times with the viewer's clock, so shift everything to "now".
shift = datetime.now(timezone.utc) - NOW


def moved(v):
    if isinstance(v, str) and v.startswith("2026-11-09T"):
        return (datetime.fromisoformat(v) + shift).isoformat()
    if isinstance(v, dict):
        return {k: moved(x) for k, x in v.items()}
    if isinstance(v, list):
        return [moved(x) for x in v]
    return v


(Path(__file__).parent / "demo-status.json").write_text(json.dumps(moved(state)))
print("wrote demo-status.json")
