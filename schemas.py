"""Tool schemas. Read-only fleet inspection plus one bounded Ollama pull; no command execution."""

FLEET_STATUS = {
    "name": "fleet_status",
    "description": (
        "Probe the user's local inference fleet (DGX Spark / Ollama / vLLM boxes "
        "registered with local-fleet) and report each node's health, load and models, the least busy box, the "
        "routing mode and which backend is the primary model now. Use when the user asks which "
        "box is up, busy or serving a model, or why Hermes is on cloud or local. Read-only."),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

FLEET_LIST_NODES = {
    "name": "fleet_list_nodes",
    "description": (
        "List the registered fleet nodes with their last recorded health, without probing. "
        "Cheaper than fleet_status when fresh health is not needed. Read-only."),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

FLEET_PULL_MODEL = {
    "name": "fleet_pull_model",
    "description": (
        "Download a model onto one Ollama node of the fleet (Ollama's own pull API). Only for "
        "nodes of kind 'ollama'. Large models take many minutes and tens of GB; confirm with the "
        "user before pulling. Returns when the pull finishes or times out."),
    "parameters": {
        "type": "object",
        "properties": {
            "node": {"type": "string", "description": "Node name or id, from fleet_list_nodes"},
            "model": {"type": "string", "description": "Ollama model tag, e.g. qwen3:14b"},
        },
        "required": ["node", "model"],
        "additionalProperties": False,
    },
}
