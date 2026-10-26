# EVIDENCE_PLAN.md — Phase 16 (Part 0)

## Structural note (needs your decision before Part D)
`AttackTrace Final Project Documentation.md` does not exist in the repo. The closest match is
`submission/AttackTrace_Documentation.md` (300 lines, sections 1–9, no subsections past 9.x). The
fix prompt's review-item table cites `§2`–`§19` and `§9.2`/`§9.5`, which don't correspond 1:1 to
this document's actual section numbers (its §9 is "Third-party resources", not a numbered run to
19). **I'll treat `submission/AttackTrace_Documentation.md` as the primary document and re-map each
review item to its actual matching section by content, not by number** — flagging in the Part D
report wherever a review item's literal section number doesn't exist. Tell me now if a different
file is actually "primary."

Also found: `backend/eval/analysis/` and `reports/fix_analysis.json` already exist (Phase 14 of this
project's own earlier history, before this conversation's visible scope) and already cover much of
Part A: `live_miss_diagnosis` (→A4), `alarm_flood` (→A5), `intervals` (→A10), `confidence_reliability`
(→A8), `sustainability` (→B4), `latency_and_timing`/`time_to_detect` (→A2, partial). I'll read and
cite these rather than recompute, except where this prompt's spec is stricter (e.g., A10 wants Wilson
intervals specifically — need to check `intervals` uses Wilson, not just normal-approx).

## Part A — from saved data only (no runs; all same-session, fast)
| Item | Source | Run needed? | Est. |
|---|---|---|---|
| A1 funnel reconciliation | `metrics.json`, `live_metrics.json`, existing incident logs | No | 10 min |
| A2 time-to-localize definitions | `fix_analysis.json.time_to_detect`/`latency_and_timing`, engine code | No (reuse + recheck definition) | 15 min |
| A3 demo vs eval gap | `submission/evidence/rehearsal*.{json,log}`, eval seed configs | No | 10 min |
| A4 LIVE miss breakdown | `fix_analysis.json.live_miss_diagnosis`, `live_metrics.json` | No (already computed, re-verify completeness) | 10 min |
| A5 alarm-flood stats | `fix_analysis.json.alarm_flood` | No (verify per-scenario breakdown present) | 10 min |
| A6 seed provenance | doc text + `eval/localization.py` seed ranges | No | 5 min |
| A7 gate transfer table | `metrics.json.ambiguity` | No | 10 min |
| A8 confidence reliability | `fix_analysis.json.confidence_reliability` | No (confirm ECE/Brier + n present) | 10 min |
| A9 explanation coverage | incident schema fields across SIM/LIVE/HAI logs | No | 10 min |
| A10 Wilson intervals | `fix_analysis.json.intervals` — confirm method is Wilson, not Wald | No (recompute only if wrong method) | 10–20 min |
| A11 auth behaviour | `backend/app/api/security.py` (already read: fail-closed outside loopback once a key or auth secret would be needed — **doc currently says "stays open", code disagrees** — will flag `NEEDS OWNER DECISION`) | No | done |

**Part A total: ~1.5–2 hrs, no approval needed (all well under 30 min each, no new runs).**

## Part B — fresh measurements (time-boxed)
| Item | Plan | Est. wall-clock | Approval? |
|---|---|---|---|
| B1 ≥20 simulated hours clean exposure, seeds 4000+ | Run headless SIM clean loop, count alarms (deployed + baseline), Poisson 95% CI | **Needs a timed dry run first** to convert sim-hours→wall-clock (current sim runs at `sim_hz=10`, loop is real-time-paced in the engine, not necessarily faster — must confirm); rough estimate 20–40 min if real-time-paced, possibly much longer if not batchable offline | **Yes — will state measured wall-clock estimate from a 2-hour dry run before committing to the full run** |
| B2 LIVE end-to-end latency, seeds 6000+ | ~10 min clean + 5 attacks, nothing else running in parallel | ~15 min | No (under 30 min) but will ask before running since it needs the plant-emulator exclusive, and the main docker stack is currently occupying those ports |
| B3 CPU/memory per process | ~15 min LIVE run, sample every 10s | ~15 min | No |
| B4 impact with/without containment, seeds 5000+, 25 attacks ×2 | Reuse existing `eval/analysis/a8_sustainability.py` pattern if it already does this; else new script | 20–30 min | Will confirm scope then proceed |

## Part C — analysis on existing models (no tuning)
| Item | Plan | Est. |
|---|---|---|
| C1 ablation (6 conditions × 50 attacks) | Reuse `eval.localization` with `AT_W_*` env overrides + a read-only flag for tie-rule off; 6 runs of the existing 50-attack eval | ~15–25 min total (depends on per-run time, will report actual) |
| C2 weight sensitivity sweep (tuning set only, step 0.05) | Loop over weight grid on seeds 400–419 only | ~15–20 min |
| C3 HAI fairer baseline | Tune baseline threshold on `test2`, report on `test1` | ~10 min (small dataset, no retraining of AttackTrace itself) |

## What I will NOT do without separate approval
- Re-run the full `eval-live` (2.75h) or the 60-min soak.
- Change any model, weight, threshold, or gate margin as a *decision* (C1/C2 only measure and report).
- Touch owner-reserved text (`[team name]`, `[member names]`, author/brand lines, LICENSE, `package.json`/`pyproject.toml` author fields).
- Push, upload, or delete any file.

## Immediate ask
1. Confirm `submission/AttackTrace_Documentation.md` is "primary" (or point me to the real file).
2. OK to proceed with all of Part A now (no runs, ~2 hrs)?
3. OK to run the B1 dry-run-then-decide step when we get there (not now)?

Waiting for your go-ahead before starting Part A.
