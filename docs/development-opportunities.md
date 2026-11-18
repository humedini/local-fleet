# Local Fleet Development Opportunities

**Generated:** 2026-11-18  
**Repository:** humedini/local-fleet  
**Version:** 0.3.4

---

## Executive Summary

Local Fleet is a Hermes plugin for health-aware routing across local inference boxes (DGX Spark, Ollama, vLLM, LiteLLM). The codebase is production-ready with no obvious bugs or TODO markers, but has several architectural opportunities for enhancement.

---

## High Priority Opportunities

### 1. Provider Adapter Pattern

**File:** `health.py`

**Current State:** Health probes for Ollama, vLLM, and LiteLLM/OpenAI are hardcoded in `health.py`. Each provider type has its own detection logic embedded in the main code.

**Opportunity:** Extract health probing into a plugin/adapter pattern where new providers can register their probe functions.

**Implementation:**
```python
# Create a registry pattern
PROVIDER_PROBES = {}

def register_probe(kind: str, probe_fn: Callable):
    PROVIDER_PROBES[kind] = probe_fn

def probe_node(node: dict) -> dict:
    kind = node.get("kind")
    if kind in PROVIDER_PROBES:
        return PROVIDER_PROBES[kind](node)
    # fallback
```

**Benefits:**
- Easy addition of new inference providers (TensorRT, Azure ML, AWS Bedrock, etc.)
- Separates concerns: core routing logic doesn't need to know about provider specifics
- Follows Hermes plugin patterns for extensibility

**Estimated Effort:** Medium

---

### 2. Enhanced Cluster Support

**Files:** `fleet.py`, `dashboard/plugin.js`, `dashboard/plugin_api.py`

**Current State:** Clusters exist but are simplified - just groups of nodes serving one model.

**Opportunity:** Add cluster-level features:

1. **Cluster Health Aggregation:**
   - Display cluster health score (percentage of healthy nodes)
   - Per-cluster load metrics
   - Cluster failover (route to another cluster if primary is down)

2. **Cross-Node Load Balancing:**
   - Distribute inference across cluster nodes based on:
     - GPU utilization
     - VRAM availability
     - Network proximity
   - Round-robin or weighted routing within cluster

3. **Cluster Management UI:**
   - Cluster creation/deletion in Desktop
   - Node assignment to clusters
   - Cluster-specific model pools

4. **Cluster Failover:**
   - Define failover behavior at cluster level
   - Pre-warm other clusters

**Estimated Effort:** High

---

## Medium Priority Opportunities

### 3. Savings Analytics Dashboard

**Files:** `traffic.py`, `reports.py`, `dashboard/plugin.js`, `dashboard/plugin_api.py`

**Current State:** Basic savings reporting exists (`receipt()` endpoint) but Dashboard UI is minimal.

**Opportunity:** Enhance with comprehensive analytics:

1. **Time-Series Charts:**
   - Daily/weekly/monthly spend avoided
   - Local vs cloud cost comparison
   - Cost per model/provider

2. **Breakdown Views:**
   - Savings by node
   - Savings by session type
   - Peak vs off-peak savings

3. **Projections:**
   - Estimated monthly savings based on current usage
   - Savings potential if all boxes were used
   - Cost avoidance trends

4. **Export Capabilities:**
   - CSV/PDF reports
   - JSON export for external tools

**Implementation Notes:**
- `traffic.py` already tracks `endpoint`, `tokens`, `duration`
- `reports.py` has `savings_receipt()` and `incident_card()`
- Dashboard already has charting infrastructure (charts.js)

**Estimated Effort:** Medium

---

### 4. Async Parallel Probing

**Files:** `health.py`, `engine.py`

**Current State:** `probe_all()` probes nodes sequentially in a loop.

**Opportunity:** Parallelize health checks with configurable concurrency.

**Implementation:**
```python
import asyncio
import httpx

async def probe_all_async(nodes: list[dict], want: str = None, 
                          max_concurrent: int = 10) -> dict:
    """Probe all nodes concurrently with semaphore limiting."""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def probe_one(node):
        async with semaphore:
            return await _probe_node_async(node, want)
    
    tasks = [probe_one(node) for node in nodes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return dict(zip([n["id"] for n in nodes], results))
```

**Benefits:**
- Faster fleet detection on large clusters
- Configurable concurrency limits
- Timeout isolation per probe

**Hermes Consideration:**
- The existing `_refresh_on_session_start` uses threading (not async)
- Could migrate to async pattern or keep threaded with connection pooling

**Estimated Effort:** Low-Medium

---

### 5. Model Compatibility Intelligence

**Files:** `readiness.py`, `health.py`

**Current State:** 
- Checks Ollama for tools/vision/context via `/api/show`
- Other providers report "not checked yet"

**Opportunity:** Expand capability checking:

1. **For vLLM:**
   - Check supported architectures from `/v1/models` response
   - Validate CUDA compute capabilities
   - Check tensor parallel support

2. **For LiteLLM:**
   - Query `/marshal/models` for tool support
   - Check context window limits via model info

3. **VRAM Requirements:**
   - Query model sizes before suggesting routing
   - Check if node has sufficient VRAM (with safety margin)

4. **Operator Support:**
   - Check if model supports tool-calling, vision, JSON mode
   - Cache results in node metadata

**Implementation:**
```python
def check_vllm_compatibility(node: dict, model: str) -> dict:
    # Query /v1/models for model info
    # Check gpu_memory, tensor_parallel_size
    # Return compatibility verdict
    
def check_litellm_compatibility(node: dict, model: str) -> dict:
    # Query /marshal/models endpoint
    # Return capabilities
```

**Estimated Effort:** Medium

---

## Low Priority Opportunities

### 6. Configuration Versioning

**File:** `store.py`

**Current State:** Fleet configuration is a single JSON file with no history.

**Opportunity:** Add version history for rollback capability:

1. **Version Table:**
   ```python
   CREATE TABLE config_versions (
       id INTEGER PRIMARY KEY,
       timestamp TEXT,
       config_json TEXT,
       reason TEXT,  # "user edit", "auto-update", etc.
       hash TEXT
   )
   ```

2. **API Endpoints:**
   - `GET /config/history` - list versions
   - `POST /config/revert` - revert to version
   - `POST /config/diff` - show diff between versions

3. **Storage Strategy:**
   - Keep only last N versions (configurable)
   - Store diffs, not full copies (optional)

**Estimated Effort:** Medium

---

### 7. Network Topology Awareness

**Proposal:** New module `network.py`

**Current State:** No awareness of network latency between boxes.

**Opportunity:** 
1. Measure latency between boxes and Hermes
2. Track packet loss/jitter
3. Prefer lower-latency paths for interactive tasks

**Implementation:**
```python
def measure_latency(node: dict, target: str = "localhost") -> float:
    """Ping or HTTP latency measurement."""
    
def network_score(node: dict) -> float:
    """Composite score based on latency, bandwidth, etc."""
```

**Integration Points:**
- Add to `pick_freest()` for side tasks
- Display in Desktop UI with map visualization

**Estimated Effort:** Medium

---

### 8. Enhanced Benchmarking

**File:** `bench.py`

**Current State:** Standalone benchmarking tool.

**Opportunity:** 
1. Integrate into health probes for warm-up measurements
2. Add model recommendation system (suggest which model to pull based on benchmarks)
3. Store historical benchmarks per node

**Estimated Effort:** Medium

---

### 9. Multi-Tenant Isolation

**Files:** `fleet.py`, `store.py`

**Current State:** No tenant awareness - single fleet per deployment.

**Opportunity:**
1. Add tenant labels to nodes
2. Route based on tenant affinity
3. Separate fleet configs per tenant

**Use Case:** Enterprise deployment with multiple teams

**Estimated Effort:** High

---

### 10. Predictive Load Estimation

**Files:** `routing.py`, `health.py`

**Current State:** Reacts to current queue length and load.

**Opportunity:**
1. Track request patterns over time
2. Use simple ML or time-series to predict load
3. Pre-emptively switch before load spikes

**Implementation:**
```python
class LoadPredictor:
    def record(self, node_id: str, load: float, timestamp: datetime):
        """Record load measurement."""
    
    def predict(self, node_id: str, horizon: float = 60.0) -> float:
        """Predict load in horizon seconds."""
```

**Estimated Effort:** High

---

## Additional Minor Opportunities

### 11. CLI Enhancements
- Add `fleet diff` to show config changes
- Add `fleet export/import` for config backup
- Add `fleet debug` for verbose troubleshooting

### 12. Desktop UI Improvements
- Model performance graphs over time
- Heatmap of node utilization
- Quick actions toolbar
- Keyboard shortcuts

### 13. Documentation
- API reference for plugin developers
- Example provider adapter implementations
- Integration guide for third-party tools

---

## Technical Debt / Code Smells

While reviewing the codebase, noted these areas for potential clean-up:

1. **Stringly-Typed IDs:** Many functions use string IDs that could be more type-safe
2. **Global State:** Some modules use global variables (`LAST` in desktop/plugin.js)
3. **Mixed Concerns:** `health.py` handles both probing AND load calculation
4. **Error Handling:** Some functions silently swallow exceptions

---

## Testing Gaps

Based on test file review:

1. No tests for async/probing behavior
2. Limited cluster-specific tests
3. No property-based tests for routing decisions
4. Desktop UI has no automated tests (browser testing would be valuable)

---

## Recommended Implementation Order

1. **Provider Adapter Pattern** (High impact, Medium effort) - Makes codebase more extensible
2. **Async Probing** (Low effort, High impact for large fleets) - Immediate performance gain
3. **Savings Dashboard** (Visible feature, Medium effort) - User-facing improvement
4. **Model Compatibility** (Medium effort, prevents errors) - Improves reliability
5. **Configuration Versioning** (Safety feature, Medium effort) - Operational improvement

---

## Files Referenced

| File | Lines | Purpose |
|------|-------|---------|
| `health.py` | ~300 | Health probes |
| `fleet.py` | ~250 | Node registry |
| `engine.py` | ~400 | Orchestration |
| `routing.py` | ~300 | Routing policy |
| `store.py` | ~350 | Configuration/state store |
| `readiness.py` | ~200 | Model capability checking |
| `traffic.py` | ~150 | Real traffic tracking |
| `reports.py` | ~200 | Reporting |
| `bench.py` | ~150 | Benchmarking |
| `dashboard/plugin_api.py` | ~200 | Desktop REST API |
| `desktop/plugin.js` | ~1000+ | Desktop UI |
| `__init__.py` | ~100 | Plugin registration |

---

## Conclusion

Local Fleet is a well-architected plugin with production-ready code. The identified opportunities are primarily architectural enhancements that would:

1. **Improve extensibility** (Provider adapters)
2. **Scale better** (Async probing, clusters)
3. **Provide better visibility** (Dashboard analytics)
4. **Increase reliability** (Compatibility checking, config versioning)

Most opportunities can be implemented incrementally without breaking existing functionality.