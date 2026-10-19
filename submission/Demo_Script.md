# Demo script (3 minutes)

**Disclosure:** the demo uses the scenarios with the strongest measured reliability; aggregate
numbers cover all scenarios.

## Before you go on stage (5 minutes ahead)
1. `docker compose up` (or the local stack). Check http://localhost:8000/api/status returns OK.
2. `.env` must hold the same value for `AT_API_KEY` and `VITE_API_KEY` (the shipped `.env.example` does). A mismatch shows `Demo locked`.
3. Open http://localhost:5173 at 1440×900 or larger. Pill reads **Normal**. SIM mode, not HAI.
4. Press **Reset** once, then **wait at least 30 s** before launching. Let the timeline run 1–2 minutes so the sparklines have data.
5. Console shows *Sensor offset*, target *LIT101*, magnitude −25.
6. Keep `submission/screenshots/` open in another window (fallback).

## Run sheet

| Time | Action | Say |
|---|---|---|
| 0:00–0:15 | Show idle twin. Point at the pill, tanks, flowing pipes. | "A water plant. Green means Normal. We attack a sensor." |
| 0:15–0:30 | Press **Launch** (Sensor offset, LIT101). | "We spoof the T1 level sensor 25% low." |
| 0:30–0:50 | Point at the LIT101 badge (`true …`) and the tank filling. | "The reading is false. The tank is really overfilling." |
| 0:50–1:15 | Pill turns **Incident**. Read the panel: origin, confidence, breakdown bar, path, T0856. | "Origin LIT101. The bar shows why: deviation, onset, causal." |
| 1:15–1:35 | Press **Split**. Point at the left flood, then the right. | "Baseline: 6 alarms. AttackTrace: one origin." |
| 1:35–1:50 | Press **Graph**, watch the pulse, press **Twin**. | "Spread follows onset order." |
| 1:50–2:25 | Press **Isolate LIT101**. Watch the tank return and the panel read **Contained**. | "Detect, locate, contain. Eval: the Top-1 click contained 40 of 48." |
| 2:25–2:35 | Click the **Report** icon. | "One-page PDF for the shift log." |
| 2:35–3:00 | Open **Metrics**. Read F1 0.904, Top-1 0.84, Contained 83%, Ambiguous 12%. | "Held-out numbers. Real HAI data is weaker: F1 0.428, and we say so." |

Rehearsed timings: for LIT101 offset, detected 1.5 s, localized 11.5 s after launch (`submission/evidence/rehearsal.md`). Containment took a mean 12.5 s of plant time after the click in the eval (`reports/metrics.json`); one live run in the screenshots took 27 s, so keep talking while it recovers.

## Fallback path
| Problem | Do this |
|---|---|
| Panel reads **Ambiguous** | Say it: "The system is unsure and shows three candidates." Click **Isolate** on the top one; if it reads **Not contained** after 30 s, click the next. |
| **Not contained** after the click | That is the honest result for a wrong node (eval: 0 of 48 contained). Click the next `Isolate <node>`. |
| Origin ranks wrong | Say the number: Top-1 is 0.84. Move to Split view. Press **Reset**, wait 30 s, relaunch. |
| `Demo locked` toast | The key differs between `AT_API_KEY` and `VITE_API_KEY`, or `AT_DEMO_MODE=false`. Fix `.env` and restart. |
| 429 on Launch | More than 10 attacks in a minute. Wait one minute. |
| Incident never appears | Launch *Actuator force* on MV101 (rehearsed: detected 1.5 s, rank 1). |
| Sparklines empty after Reset | Wait 30 s. A cold detector after Reset needs warm-up. |
| WebSocket drops | Reload the page. It reconnects on its own (500 ms to 8 s backoff). |
| Docker or backend down | Show `submission/screenshots/` (01 to 10), `submission/evidence/sample_incident_report.pdf` and `submission/evidence/rehearsal.md`. |
| Metrics page 404 | Show `reports/metrics.json` and the README results table. |
| Need real data | Click the **HAI** toggle (needs `data/hai/`). The first incident takes about a minute. Isolate is disabled there. |
| Asked about a real protocol | Click the **LIVE** toggle (needs `make emulator` + `make live-train` beforehand). It shows a calibrating ring, then runs the same scenarios over a real Modbus TCP read against our own emulated plant — not physical hardware, and we say so. Isolate is disabled there too (read-only backend). |
