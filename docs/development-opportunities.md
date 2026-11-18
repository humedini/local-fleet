# Local Fleet Development Opportunities

**Generated:** 2026-11-18  
**Repository:** humedini/local-fleet  
**Version:** 0.3.4

---

## Executive Summary

Local Fleet is a Hermes plugin for health-aware routing across local inference boxes (DGX Spark, Ollama, vLLM, LiteLLM). The codebase is **production-ready** with:
- ✅ Parallel health probing (ThreadPoolExecutor, PROBE_CONCURRENCY=8)
- ✅ Cluster support (nodes with `members` field)
- ✅ Full Desktop UI with fitness map
- ✅ Complete test coverage

**Key finding:** The "async parallel probing" opportunity is already implemented. The `_LOAD` dict in `health.py` is the extension point for new providers.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Local Fleet                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐         │
│  │ fleet.py    │────▶│engine.py    │────▶│routing.py   │         │
│  │ (registry)  │     │(orchestrate)│     │(decisions)  │         │
│  └─────────────┘     └─────────────┘     └─────────────┘         │
│         │                              │  │                    │
│         ▼                              ▼  ▼                    │
│  ┌─────────────┐     ┌─────────────┐  ┌─────────────┐           │
│  │ health.py   │────▶│readiness.py │  │traffic.py   │           │
│  │ (probes)    │     │ (model caps)│  │ (stats)     │           │
│  └─────────────┘     └─────────────┘  └─────────────┘           │
│                                                                  │
│  Hermes Integration:                                             │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ __init__.py: on_session_start, pre_tool_call,               ││
│  │               post_api_request, api_request_error,          ││
│  │               post_auxiliary_call                           ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ CLI (cli.py) │  │Desktop UI    │  │REST API      │           │
│  │              │  │(plugin.js)   │  │(plugin_api.py)│          │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Already Exists

### 1. **Parallel Probing** (health.py:193-201)
```python
def probe_all(nodes: list[dict], timeout: float = 2.0, want="",
              transport: httpx.BaseTransport | None = None) -> dict[str, dict]:
    """Probe nodes in parallel; returns {node_id: snapshot}."""
    with ThreadPoolExecutor(max_workers=min(PROBE_CONCURRENCY, len(nodes))) as pool:
        futures = {n["id"]: pool.submit(probe_node, n, client, want) for n in nodes}
        return {nid: f.result() for nid, f in futures.items()}
```

### 2. **Cluster Support** (fleet.py:200-250)
- Nodes can have `members` field pointing to other node IDs
- Clusters must have 2+ members, cannot contain themselves
- Member removal requires removing from clusters first

### 3. **Provider Extension Point** (health.py:186)
```python
_LOAD = {"ollama": _ollama_load, "vllm": _vllm_load}
```
- Only `ollama` and `vllm` have load probes
- LiteLLM/OpenAI-compatible do latency-only probing

### 4. **Ready Monitoring** (doctor.py)
- HTTP address privacy checks
- Watch heartbeat tracking
- Plain HTTP warnings

### 5. **Traffic Recording** (traffic.py)
- Records endpoint, tokens, duration
- Privacy scrubbing available
- Summarizes savings

---

## Identified Development Opportunities

### HIGH PRIORITY

#### 1. Expand Provider Support

**Current state:** Only `ollama` and `vllm` have load probes in `_LOAD`. LiteLLM/OpenAI-compatible only check latency.

**Opportunity:** Add load probing for:
- **LiteLLM:** Query `/stats` or similar endpoint if available
- **OpenAI-compatible:** Use `/v1/engines` or similar
- **Custom providers:** Allow registration of new probe functions

**Files:** `health.py`, `constants.py`

**Why not urgent:** Core functionality works; this is for advanced deployments.

---

#### 2. Enhance Cluster Features

**Current state:** Basic cluster membership in `fleet.py`, but no cluster-level operations.

**Opportunity:** Add:
1. **Cluster health aggregation:** Percentage of healthy nodes
2. **Cluster metrics:** Aggregate load, member status display
3. **Cluster failover:** Route to another cluster if primary fails
4. **Cluster-specific routing:** Prefer cluster members for consistency

**Files:** `fleet.py`, `routing.py`, `dashboard/plugin.py`

**Current limitation:** Clusters exist in model but Desktop UI has minimal cluster-specific display.

---

#### 3. Model Compatibility Intelligence

**Current state:** `readiness.py` only checks Ollama. Others return "not checked yet".

**Found in `readiness.py`:**
```python
def inspect(client, node, model, ps_context=None):
    if node.get("kind") != "ollama":
        out["source"] = f"{node.get('kind')} does not report capabilities"
        return out
```

**Opportunity:** Add capability checking for:
- **vLLM:** Query model info endpoint
- **LiteLLM:** Check model capabilities via API
- **OpenAI-compatible:** Use `/v1/models` detail if available

**Files:** `readiness.py`, `health.py`

---

### MEDIUM PRIORITY

#### 4. Savings Analytics Enhancement

**Current state:** 
- `traffic.summarize()` tracks data
- `reports.savings_receipt()` generates markdown
- Dashboard (`plugin.js`) shows basic stats

**Opportunity:** Add to Dashboard:
- Time-series charts (daily/weekly savings)
- Per-node breakdown
- Per-model breakdown
- Cost projections

**Found in `plugin.js`:** `SavingsPanel` component is basic.

**Files:** `traffic.py`, `reports.py`, `dashboard/plugin.js`, `dashboard/plugin_api.py`

---

#### 5. Network Topology Awareness

**Current state:** No network awareness; routes purely on load/latency.

**Opportunity:**
- Measure latency between boxes
- Track network availability
- Prefer lower-latency paths for interactive sessions

**Files:** New `network.py`, integration with `routing.py`

---

### LOWER PRIORITY

#### 6. Configuration Version Control

**Current state:** `fleet.json` and `state.json` have no version history.

**Opportunity:**
- Add history/diff capability
- Implement rollback feature
- Add `fleet export` command

**Files:** `store.py`, `cli.py`

---

#### 7. Enhanced Benchmarking

**Current state:** `bench.py` standalone, not integrated into health checks.

**Opportunity:**
- Add to health checks for warm-up
- Add model recommendations
- Store historical benchmarks

**Note:** `bench.py` is well-designed and ready for integration.

---

## Testing Gaps

Based on test file review:

| Test File | Coverage | Gaps |
|-----------|----------|------|
| `test_health.py` | High | Cluster probing, new providers |
| `test_routing.py` | High | Network latency weighting |
| `test_engine.py` | High | Cluster scenarios |
| `test_gaps.py` | Focused | Specific gaps documented |

**Missing:**
- Integration tests for clusters
- Frontend UI tests
- Property-based tests for routing decisions

---

## Recommendations

### For Implementation

1. **First: Provider adapter documentation** - The `_LOAD` dict exists but isn't documented for extension
2. **Second: Cluster UI enhancements** - Add cluster-specific display in Dashboard
3. **Third: Model compatibility** - Expand beyond Ollama-only checking

### Architecture Strengths

1. **Clean separation of concerns** - `health.py`, `routing.py`, `engine.py` have distinct roles
2. **Privacy by design** - `render.scrub()` everywhere
3. **Drift detection** - Side task drift is well-implemented
4. **Test coverage** - Tests cover core functionality

### Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `health.py` | ~200 | Health probes, `_LOAD` extension point |
| `readiness.py` | ~100 | Model capability checking (Ollama only) |
| `routing.py` | ~150 | Routing policy, `pick_freest()` |
| `fleet.py` | ~260 | Node registry, cluster membership |
| `store.py` | ~150 | Config/state persistence |
| `bench.py` | ~150 | Performance benchmarking |
| `traffic.py` | ~100 | Traffic recording |
| `dashboard/plugin.js` | 1464 | Desktop UI |
| `dashboard/plugin_api.py` | ~230 | Desktop REST API |

---

## Conclusion

Local Fleet is well-engineered with production-ready code. The major opportunities are:

1. **Provider adapter documentation** (quick win)
2. **Cluster UI enhancements** (medium effort, visible impact)
3. **Model compatibility for vLLM/LiteLLM** (medium effort)

The "parallel probing" is already implemented - no opportunity there.

The codebase follows Hermes plugin patterns well with hooks, tools, and desktop integration.