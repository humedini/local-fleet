"""`hermes fleet …`: argparse setup and handlers."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config_write, doctor, engine, store
from .aux import DEFAULT_TASKS as AUX_DEFAULT, TASKS as AUX_TASKS
from .constants import KINDS, MODES, OSES, VENDORS
from .fleet import FleetError, public_node
from .render import decision_text, nodes_table, status_text, target_text


def setup_argparse(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="fleet_command", metavar="<command>")

    sub.add_parser("setup", help="Guided first run: add a node, pick a mode and a cloud backup")
    p = sub.add_parser("add", help="Register a node")
    p.add_argument("--name", required=True)
    p.add_argument("--url", required=True, help="OpenAI-compatible base URL, e.g. http://192.168.1.50:11434/v1")
    p.add_argument("--kind", choices=KINDS, default="ollama")
    p.add_argument("--label", action="append", default=[], help="Repeatable, e.g. --label lan")
    p.add_argument("--api-key-env", help="NAME of the env var holding this node's key (never the key)")
    p.add_argument("--capacity-gb", type=float, help="Model memory on the box, for a real free-memory figure")
    p.add_argument("--vendor", choices=VENDORS, help="Accelerator vendor, for the Desktop icon (else guessed from the name)")
    p.add_argument("--os", dest="os_name", choices=OSES, help="Operating system, for the Desktop icon")
    for name, hlp in (("rm", "Remove a node"), ("enable", "Enable a node"), ("disable", "Disable a node")):
        sub.add_parser(name, help=hlp).add_argument("node", help="id or name")
    p = sub.add_parser("list", help="List nodes with their last health")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("status", help="Check every box and show where Hermes would go (changes nothing)")
    p.add_argument("--json", action="store_true")
    sub.add_parser("doctor", help="Check the plugin is ready to route")
    p = sub.add_parser("watch", help="Probe and re-apply the policy on an interval (failover + failback)")
    p.add_argument("--interval", type=float, help="Seconds between probes (default: probe_interval_s)")
    p.add_argument("--once", action="store_true", help="One tick, then exit (for cron)")
    p = sub.add_parser("use", help="Switch Hermes to a box now (kept while it is up), or --best for the least busy one")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("node", nargs="?", help="id or name")
    g.add_argument("--best", "--freest", dest="freest", action="store_true", help="the least busy box that has your model")
    p = sub.add_parser("mode", help="Show or set the routing mode")
    p.add_argument("mode", nargs="?", choices=MODES)
    p = sub.add_parser("cloud", help="Show or set the cloud target used for prefer-cloud and failover")
    p.add_argument("provider", nargs="?")
    p.add_argument("model", nargs="?")
    p = sub.add_parser("model", help="Show or set the model id to run on local nodes ('' = pick per node)")
    p.add_argument("model", nargs="?")
    p = sub.add_parser("bench", help="Measure generation speed (tokens/sec) on each box")
    p.add_argument("node", nargs="*", help="ids or names (default: every enabled box)")
    p.add_argument("--load", action="store_true", help="Load the model if it is not in memory (slow, uses memory)")
    p = sub.add_parser("set", help="Set a box's vendor / OS (for the Desktop icons), labels or capacity")
    p.add_argument("node", help="id or name")
    p.add_argument("--vendor", choices=VENDORS)
    p.add_argument("--os", dest="os_name", choices=OSES)
    p.add_argument("--label", action="append", help="Replaces the labels; repeatable")
    p.add_argument("--capacity-gb", type=float)
    sub.add_parser("stats", help="Real traffic per box this week: calls, tok/s, latency, local share, spend avoided")
    p = sub.add_parser("price", help="Cloud price per million tokens, for the spend-avoided figure")
    p.add_argument("input", type=float)
    p.add_argument("output", type=float)
    p.add_argument("--currency", default=None, help="ISO 4217 code (GBP, EUR, USD, …) or £ € $ ¥")
    p = sub.add_parser("aux", help="Run side tasks (titles, compression, …) on the least busy box")
    p.add_argument("action", choices=("on", "off", "status"))
    p.add_argument("--tasks", help=f"Comma list from {', '.join(AUX_TASKS)} (default: {', '.join(AUX_DEFAULT)})")
    p = sub.add_parser("delegate", help="Run subagents on the fleet (delegation backend 'fleet')")
    p.add_argument("action", choices=("on", "off", "status"))
    sub.add_parser("endpoint", help="Show the primary endpoint Hermes is using")
    sub.add_parser("restore", help="Put back the primary you had before local-fleet")
    parser.set_defaults(func=main)


def _active_id() -> str:
    return (store.load_state().get("applied") or {}).get("node_id", "")


def _apply_and_report(**kw) -> int:
    d = engine.apply_policy(**kw)
    print(status_text(store.fleet().nodes, d, _active_id()))
    return 0 if not d.get("warning") else 1


def _setup() -> int:
    if not sys.stdin.isatty():
        print("setup is interactive; use `hermes fleet add`, `mode` and `cloud` in scripts")
        return 2
    f = store.fleet()
    if not f.nodes:
        print("First node. An Ollama box is usually http://<host>:11434/v1")
        url = input("  base URL: ").strip()
        name = input("  name [spark1]: ").strip() or "spark1"
        kind = input(f"  kind {KINDS} [ollama]: ").strip() or "ollama"
        try:
            f.add(name, url, kind)
        except FleetError as e:
            print(f"  ✗ {e}")
            return 1
    settings, f, results = engine.probe()
    print(nodes_table(f.nodes))
    mode = input(f"\nMode {MODES} [{settings['mode']}]: ").strip() or settings["mode"]
    if mode not in MODES:
        print(f"  ✗ unknown mode {mode}")
        return 1
    store.write_setting("mode", mode)
    primary = config_write.current_primary()
    suggest = primary if primary.get("provider") not in (None, "custom") else {}
    cp = input(f"Cloud provider for backup [{settings['cloud_provider'] or suggest.get('provider', '')}]: ").strip()
    cp = cp or settings["cloud_provider"] or suggest.get("provider", "")
    cm_default = settings["cloud_model"] or (suggest.get("default", "") if suggest.get("provider") == cp else "")
    cm = input(f"Cloud model [{cm_default}]: ").strip() or cm_default
    store.write_setting("cloud_provider", cp)
    store.write_setting("cloud_model", cm)
    common = sorted(set.intersection(*[set(n.get("models") or []) for n in f.enabled()])) if f.enabled() else []
    if common:
        print("Models every node has: " + ", ".join(common[:12]))
    dm = input(f"Model to run locally ('' = pick per node) [{settings['default_model']}]: ").strip()
    store.write_setting("default_model", dm or settings["default_model"])
    if input("Route now? [Y/n] ").strip().lower() in ("", "y", "yes"):
        return _apply_and_report()
    return 0


def _watch(args) -> int:
    interval = args.interval or float(store.read_settings()["probe_interval_s"])
    last = None
    try:
        while True:
            d = engine.apply_policy(auto_bench=True)
            key = json.dumps(d.get("target"), sort_keys=True)
            stamp = time.strftime("%H:%M:%S")
            if key != last or d.get("applied"):
                print(f"[{stamp}] {target_text(d['target'])} ({d['reason']})"
                      f"{' — applied' if d.get('applied') else ''}"
                      f"{' — ' + d['warning'] if d.get('warning') else ''}", flush=True)
                last = key
            if args.once:
                return 0
            time.sleep(max(2.0, interval))
    except KeyboardInterrupt:
        print("\nwatch stopped")
        return 0


def stats_text() -> str:
    from . import traffic
    s = store.read_settings()
    t = traffic.summarize(traffic.load(), (float(s["price_in_per_m"] or 0), float(s["price_out_per_m"] or 0)))
    names = {n["id"]: n["name"] for n in store.fleet().nodes}
    lines = [f"  {'box':<12} {'calls':>6} {'errors':>6} {'tok/s':>7} {'latency':>8} {'tokens':>9}"]
    for nid, b in sorted(t["boxes"].items(), key=lambda kv: -kv[1]["calls"]):
        lines.append(f"  {names.get(nid, nid):<12} {b['calls']:>6} {b['errors']:>6} {b['tps'] or '-':>7} "
                     f"{(str(b['latency_s']) + 's') if b['latency_s'] else '-':>8} {b['in'] + b['out']:>9}")
    if not t["boxes"]:
        lines.append("  no traffic to fleet boxes yet this week")
    share = f"{t['local_share'] * 100:.0f}%" if t["local_share"] is not None else "-"
    lines.append(f"\nlocal tokens {t['local_tokens']:,} · cloud tokens {t['cloud_tokens']:,} · local share {share}")
    if t["saved"] is not None:
        lines.append(f"spend avoided this week: {store.format_money(t['saved'], s['currency'])}")
    else:
        lines.append("spend avoided: set a cloud price with hermes fleet price <in> <out> [--currency GBP]")
    lines.append("(tok/s here is effective: real calls including prompt processing; hermes fleet bench gives decode speed)")
    return "\n".join(lines)


def _aux(args) -> int:
    if args.action == "status":
        st = store.load_state().get("aux_applied")
        print(f"side tasks: {', '.join(st['tasks'])} → {st['node_name']} · {st['model']}" if st else "side tasks: off")
        return 0
    if args.action == "off":
        tasks = engine.aux_off()
        print(f"side tasks back on their own settings: {', '.join(tasks)}" if tasks else "side tasks were not on the fleet")
        return 0
    tasks = [t.strip() for t in (args.tasks or ",".join(AUX_DEFAULT)).split(",") if t.strip()]
    bad = [t for t in tasks if t not in AUX_TASKS]
    if bad:
        print(f"✗ unknown task(s): {', '.join(bad)}; choose from {', '.join(AUX_TASKS)}")
        return 1
    store.write_setting("aux_tasks", tasks)
    d = engine.apply_policy(dry_run=True, aux_follow=True)  # side tasks only; the main route is untouched
    print(d.get("aux") or "side tasks: already on the least busy box")
    return 0


def _delegate(action: str) -> int:
    if action == "status":
        b = store.delegation_backend()
        print(f"delegation backend: {b}{' (subagents run on the fleet)' if b == 'fleet' else ''}")
        return 0
    store.set_delegation_backend("fleet" if action == "on" else "default")
    print("subagents " + ("run on the fleet" if action == "on" else "back on the default route") +
          " from each session's next session (/new), or now with /delegation " + ("fleet" if action == "on" else "default") + " --now")
    return 0


def _show_or_set(key: str, value, label: str) -> int:
    if value is None:
        print(f"{label}: {store.read_settings()[key] or '(none)'}")
        return 0
    store.write_setting(key, value)
    print(f"{label} set to {value or '(none)'}")
    return 0


def main(args) -> int:
    cmd = getattr(args, "fleet_command", None) or "status"
    try:
        code = _dispatch(cmd, args)
    except FleetError as e:
        print(f"✗ {e}")
        code = 1
    if code:
        raise SystemExit(code)
    return 0


def _dispatch(cmd: str, args) -> int:
    if cmd == "setup":
        return _setup()
    if cmd == "add":
        node = store.fleet().add(args.name, args.url, args.kind, args.label, args.api_key_env,
                                 capacity_gb=args.capacity_gb, vendor=args.vendor, os_name=args.os_name)
        print(f"added {node['name']} ({node['id']}) {node['base_url']} — probe with: hermes fleet status")
        return 0
    if cmd in ("rm", "enable", "disable"):
        f = store.fleet()
        node = f.remove(args.node) if cmd == "rm" else f.set_enabled(args.node, cmd == "enable")
        print(f"{ {'rm': 'removed', 'enable': 'enabled', 'disable': 'disabled'}[cmd]} {node['name']}")
        return 0
    if cmd == "list":
        f, applied = store.fleet(), store.load_state().get("applied") or {}
        print(json.dumps([public_node(n) for n in f.nodes], indent=2) if args.json
              else nodes_table(f.nodes, applied.get("node_id", "")))
        return 0
    if cmd == "status":
        d = engine.apply_policy(dry_run=True)
        if args.json:
            print(json.dumps({"decision": d, "nodes": [public_node(n) for n in store.fleet().nodes]}, indent=2))
        else:
            text = status_text(store.fleet().nodes, d, _active_id())
            if d["changed"]:
                text += "\n(status changes nothing: `hermes fleet use --best` applies this route)"
            print(text.replace("applied: already the primary", "already the primary"))
        return 0
    if cmd == "doctor":
        ok, lines = doctor.run()
        print("\n".join(lines))
        return 0 if ok else 1
    if cmd == "watch":
        return _watch(args)
    if cmd == "use":
        return _apply_and_report(unpin=True) if args.freest else _apply_and_report(pin=args.node)
    if cmd == "mode":
        if args.mode is None:
            return _show_or_set("mode", None, "mode")
        store.write_setting("mode", args.mode)
        print(f"mode set to {args.mode}")
        return _apply_and_report(unpin=True)
    if cmd == "cloud":
        if args.provider is None:
            s = store.read_settings()
            print(f"cloud: {s['cloud_provider'] or '?'}/{s['cloud_model'] or '?'}")
            return 0
        if not args.model:
            print("✗ give both: hermes fleet cloud <provider> <model>")
            return 1
        store.write_setting("cloud_provider", args.provider)
        store.write_setting("cloud_model", args.model)
        added = config_write.ensure_fallback(args.provider, args.model)
        print(f"cloud set to {args.provider}/{args.model}"
              f"{' and added to fallback_providers' if added else ' (already on fallback_providers)'}")
        return 0
    if cmd == "model":
        return _show_or_set("default_model", args.model, "local model")
    if cmd == "bench":
        nodes, out = engine.bench(args.node or None, load=args.load)
        for n in nodes:
            r = out.get(n["id"], {})
            if r.get("tps"):
                extra = f", prompt {r['prompt_tps']:g} tok/s" if r.get("prompt_tps") else ""
                extra += f", first token {r['ttft_ms']} ms" if r.get("ttft_ms") else ""
                print(f"  {n['name']:<12} {r['tps']:>6.1f} tok/s  {r['model']}{extra}")
            else:
                print(f"  {n['name']:<12}  skipped: {r.get('skipped') or r.get('error')}")
        return 0
    if cmd == "set":
        node = store.fleet().update(args.node, vendor=args.vendor, os=args.os_name, labels=args.label,
                                    capacity_gb=args.capacity_gb)
        from .fleet import platform
        p = platform(node)
        print(f"{node['name']}: vendor={p['vendor'] or '?'} os={p['os'] or '?'} labels={','.join(node['labels']) or '-'}")
        return 0
    if cmd == "stats":
        print(stats_text())
        return 0
    if cmd == "price":
        try:
            code = store.currency_code(args.currency) if args.currency else store.read_settings()["currency"]
        except ValueError as e:
            print(f"✗ {e}")
            return 1
        store.write_setting("price_in_per_m", args.input)
        store.write_setting("price_out_per_m", args.output)
        store.write_setting("currency", code)
        print(f"cloud price set: {store.format_money(args.input, code)} in / {store.format_money(args.output, code)} out per million tokens")
        return 0
    if cmd == "aux":
        return _aux(args)
    if cmd == "delegate":
        return _delegate(args.action)
    if cmd == "endpoint":
        p = config_write.current_primary()
        applied = store.load_state().get("applied")
        print(f"primary: {p.get('provider', '?')} model={p.get('default', '?')}"
              f"{' base_url=' + p['base_url'] if p.get('base_url') else ''}")
        print(f"routed by local-fleet: {target_text(applied) if applied else 'no'}")
        return 0
    if cmd == "restore":
        original = engine.restore()
        print("nothing to restore" if original is None else
              f"restored primary: {original.get('provider', '?')} model={original.get('default', '?')}")
        return 0
    print(decision_text(engine.apply_policy(dry_run=True)))
    return 0
