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
    # Lower tiers, in order: used on boxes without default_model when no box has it.
    "fallback_models": [],
    # How much freer (load_proxy, 0..1) another node must be before a healthy active node is
    # swapped out. Stops two equally idle boxes trading places on every watch tick.
    "switch_margin": 0.25,
    # Seconds between automatic speed benches per box (watch, session start, Desktop probe); 0 = off.
    "bench_interval_s": 900.0,
    # Load the model on a box before switching Hermes to it (Ollama), and how long to wait.
    "warm_before_switch": True,
    "warm_timeout_s": 120.0,
    # Keep the routed model in memory while Hermes is routed to an Ollama box (no cold load after
    # idle time); released back to Ollama's normal idle timer when routing moves away.
    "keep_loaded": False,
    # Hide box addresses in the Desktop and the terminal (screen recordings, demos).
    "hide_addresses": False,
    # Auxiliary tasks to run on the least busy box (hermes fleet aux on); empty = off.
    "aux_tasks": [],
    # Cloud prices per million tokens (input, output) for the "spend avoided" figure; 0 = not shown.
    "price_in_per_m": 0.0,
    "price_out_per_m": 0.0,
    "currency": "USD",  # ISO 4217 code; the Desktop formats amounts in the viewer's locale
}

PROBE_CONCURRENCY = 8
FLEET_FILE = "fleet.json"
STATE_FILE = "state.json"
