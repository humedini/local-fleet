# Changelog

## Unreleased

- Works with Hermes 0.23.0 (The Hearth Release). CI now runs Hermes's `plugins validate` and `plugins doctor` against 0.22.7 and 0.23.0; no code changes were needed.
- Disclosed the one undocumented Hermes import (`agent.usage_pricing.get_pricing_entry`, flagged by validate under catalog rule 9) in the README and the catalog listing. It is guarded: if it moves, savings shows "unavailable" and `hermes fleet price` still works.
- Flight recorder redesigned as its own panel: 24-hour tiles (route changes, real outages, time on your boxes, last served), a 24-hour strip with a tick per event, a filter switch (configured, served, health, simulated) with counts, and each event in its own box with a diamond marker coloured by meaning (a box coming back is green, going down is red), grouped by day with clock times. Rehearsals have dashed outlines. Shows 12 events, or up to 120 with *Show all*. The rehearsal packs moved into one *Rehearse* menu, with what each does; *End packs* appears only while a pack's rehearsal runs, and the Simulated filter only when there are simulated events.

## 0.3.0 (2026-11-06)

- Guided demo on the Local Fleet page: about 80 seconds through why, a rehearsed outage to cloud and back, drift, readiness, savings and the doctor, on the real panels, with simulation labels, Pause, Skip, Exit and Esc.
- Rehearsal packs: Local A down, Force cloud hop, Recover + drift (`hermes fleet pack`), with recorder markers and a cleanup that ends only their own rehearsals. While a rehearsal runs, no warm-up and no keep-loaded hold on the stand-in box.
- Incident card (`hermes fleet incident`, *Copy incident card*) and savings receipt (`hermes fleet receipt`, *Copy receipt*): Markdown (and JSON) always scrubbed with the privacy filter.
- Cloud refused toast in private mode, naming the cloud route held back, only when one is configured.
- Catalog storyboard generator (`scripts/screenshots/storyboard.sh`): three stamped frames from synthetic data.

## 0.2.1 (2026-11-06)

- The savings baseline needs no typing: with no price set, the cloud backup's rates come from Hermes's own rate card (`agent.usage_pricing`), at most daily, in USD. A subscription route such as `openai-codex` uses the same model's API list price and says so. `hermes fleet price` shows the rates in use; `--auto` drops your own.
- Desktop: drawers start below the window title bar, so Close is no longer under the window controls.
- README: running the watch loop as a systemd user service.

## 0.2.0 (2026-11-06)

- Private inference fails closed: the primary is held on a registered box when none is up, cloud entries come off `fallback_providers`, managed side tasks lose their cloud fallback, subagents move to the `fleet` backend. Status is read from Hermes's actual config and says *not in force* when anything Local Fleet does not own points at cloud.
- One privacy filter for every output path (Desktop REST and errors, inspector, recorder, CLI text and JSON, `/fleet`, agent tools, export); the recorder masks addresses before storing.
- Side-task drift covers provider, model, base_url, fallback_chain and new credential fields; Stop managing no longer reads as drift.
- Doctor: plain HTTP to a public address warning restored; the watch check uses the loop's own heartbeat.
- Readiness threshold exported and used by the Desktop; the savings baseline is explicit; the Why drawer shows each box's probe age.
- Desktop toggles answer with the state after the change.

## 0.1.0 (2026-11-06)

- First release: fleet registry, health and load probes, least-busy routing with fallback model tiers, cloud failover and fail-back, Desktop chip and fleet page, operations (why inspector, flight recorder, rehearsals, maintenance, drift, readiness, savings, doctor), subagents and side tasks on the fleet, keep-loaded, clusters.
