# Presenter cheat sheet (one page)

*Numbers pending: the primary/backup click-path picks below come from `reports/demo_trials.json`
(Phase 14 C1, 30 fresh trials per pair) — placeholder until that run finishes; this file gets a
second pass once it does.*

## Click path (SIM)
1. **Reset.** Wait 30 s (detector warm-up).
2. **Attack console**: scenario = `<primary scenario>`, target = `<primary target>`, **Launch**.
3. Watch the pill turn **Incident** — point at the twin: reported value vs `true …`.
4. Panel names the origin, confidence breakdown, path, MITRE tag.
5. **Isolate `<target>`** → pill reads **Contained**.
6. **Split** → point at the baseline flood vs the one origin.
7. **Metrics** → headline numbers (below).

## Headline numbers (say the n, not just the %)
| Claim | Number | Definition | n |
|---|---|---|---|
| Detection F1 | 0.904 | precision/recall over all 2 Hz samples, 50 held-out attacks + 20 clean runs | 50 attacks, 20 clean |
| False alarms | 0.0/h | rising alert edges per clean hour | 20 clean 5-min runs |
| Origin Top-1 | 0.84 [0.71, 0.92] 95% CI | top-ranked candidate == true origin | 50 |
| Origin Top-3 | 1.00 | true origin in top 3 | 50 |
| Median time to detect | see `reports/fix_analysis.json:time_to_detect` | attack start → first alert | 50 |
| Top-1 isolate contains | 40/48 (83%) | the click an operator actually makes | 48 detected |
| LIVE detection F1 | 0.951 | same definition, real Modbus TCP protocol | 30 |
| LIVE Top-1 / Top-3 | 0.833 / 0.867 | same definition, over the real protocol path | 30 |
| HAI (real data) F1 | 0.428 strict / 0.915 point-adjusted | real recorded dataset, not the simulator | 28 |

*LIVE validates the real-protocol integration path (same simulator physics behind real Modbus
TCP), not generalization to a physical plant. HAI is the independent evidence of that.*

## If Top-1 is wrong
Say it plainly: "Top-1 is right 84% of the time on held-out data — this is the other 16%." Point at
**Top-3** (100%) and the **Ambiguous** flag if it's showing. Click the next candidate's isolate
button. Do not re-launch to get a different result.

## If LIVE fails mid-demo
Switch back to **SIM** — same UI, same guarantees, no real-time dependency on the emulator's health.
Say: "LIVE needs a live Modbus connection to our emulator; SIM is the same detector, same code
path, no network dependency." Do not restart the whole stack on stage.

## Fast facts if asked
- **Is LIVE real hardware?** No — a real protocol (Modbus TCP) against our own emulated plant, not
  validated on physical hardware. Say this before anyone asks.
- **Is the confidence calibrated?** It's a temperature-scaled softmax score, not a formally
  calibrated probability — ECE ~0.14 on held-out SIM data (`reports/fix_analysis.json`).
- **Did you pick the demo scenario?** Yes, openly — the scenario with the strongest measured
  reliability (see click path above); aggregate numbers above cover all five scenarios, not just
  the one we demo.

*Full click-path/scenario detail: `Demo_Script.md`. Judge Q&A: `QA_Prep.md`.*
