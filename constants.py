"""Names and defaults shared across local-fleet."""

PLUGIN = "local-fleet"
TOOLSET = "local_fleet"

KINDS = ("ollama", "vllm", "litellm", "openai-compatible")
MODES = ("prefer-local", "prefer-cloud", "auto")
VENDORS = ("nvidia", "apple", "amd", "intel", "other")
OSES = ("linux", "macos", "windows")

DEFAULTS = {
    "mode": "auto",
    "cloud_provider": "openrouter",
    "cloud_model": "",
    "probe_timeout_s": 2.0,
    "probe_interval_s": 30.0,
    "failback_enabled": True,
    "prefer_labels": [],
    "default_model": "",
    # How much freer (load_proxy, 0..1) another node must be before a healthy active node is
    # swapped out. Stops two equally idle boxes trading places on every watch tick.
    "switch_margin": 0.25,
    # Seconds between automatic speed benches per box (watch, session start, Desktop probe); 0 = off.
    "bench_interval_s": 900.0,
}

PROBE_CONCURRENCY = 8
FLEET_FILE = "fleet.json"
STATE_FILE = "state.json"
