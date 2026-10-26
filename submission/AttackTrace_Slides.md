# AttackTrace
Sustainathon 2026 · AI-07 Attack-Localization

- Detects an industrial attack
- Names the origin component
- Traces how it spread
- Live, on a water-plant twin

Notes: Open on the result: one origin instead of an alarm flood. Everything shown today runs in the demo.

---

# The problem

- One attack triggers many alarms
- 3σ baseline: 6 alarms for one attack
- Baseline false alarms: 3.6 per hour
- Baseline names the origin: 68% of time
- Operators need the cause, not alarms

Notes: The 6 alarms were measured live on a LIT101 sensor offset. The 3.6 per hour and 68% come from `reports/metrics.json`.

---

# Approach

- Detect: forecast error on a causal graph
- Localize: three signals rank the origin
- Trace: path ordered by onset time
- Explain: action plus MITRE ATT&CK tag
- CPU only, 2 Hz stream

Notes: Each stage is its own module. The API contract between backend and UI is frozen.

---

# Three signals

- Deviation (0.6): who moved the most
- Onset (0.2): who moved first
- Causal (0.2): who explains the others
- Tie rule: sensor versus its PLC
- Top-1 rose from 0.66 to 0.88

Notes: Each signal alone fails somewhere: deviation ties sensor and PLC, onset is noisy, causal ignores size. The 0.66 to 0.88 gain is an iterative tuning win, not a held-out result: the tie rule's own logic was designed by observing failures on that 50-attack set and iterating until they resolved, then fixed as code — say so plainly if asked, don't let "held-out" overstate it. The final, independently-measured set gives Top-1 0.84.

---

# Architecture

- Simulator, HAI replay, or a real Modbus TCP read feeds engine
- Graph-attention forecaster scores each node
- Localizer ranks origin, builds path
- FastAPI streams state over WebSocket
- React UI: twin, graph, split, metrics

Notes: Same pipeline runs on the simulator, on real HAI data, and over a real industrial protocol. See the Mermaid diagram in the documentation.

---

# Live demo

- Launch sensor offset on LIT101
- Pill turns Incident within seconds
- Panel names LIT101, path, action, T0856
- Split view: baseline flood versus one origin
- Press Isolate; watch the plant recover

Notes: Rehearsal: 15 of 15 attacks detected, origin ranked first in 13. Demo script is in `Demo_Script.md`.

---

# Detect → Locate → Contain

- Isolate button acts on the answer
- True origin isolated: 48 of 48 contained
- Top-1 click contained 40 of 48
- Wrong node isolated: 0 of 48 contained
- Close calls shown as Ambiguous, top 3

Notes: Containment needs the real origin to be isolated and every node score to stay low for 5 s. The simulator knows whether an attack still acts, so the 48 of 48 row is partly by construction. The honest figure is the Top-1 click: 40 of 48.

---

# Results: simulator

- Detection F1 0.904 versus baseline 0.766
- False alarms 0.0 versus 3.6 per hour
- Origin Top-1 0.84, Top-3 1.00
- Baseline Top-1 0.68, Top-3 0.86
- Time to localize: 23.3 s

Notes: 50 held-out attacks and 20 clean runs on unseen seeds. Weakest case is slow sensor ramp: Top-1 0.5.

---

# Results: real HAI data

- 28 attacks, held out, never tuned on
- 22 of 28 detected
- Strict F1 0.428, recall 0.276
- Process Top-1 0.909 on detected attacks
- Always answering P1 scores 0.864

Notes: Strict F1 is low because most attacks are slow. Point-adjusted F1 is 0.915 but it is the optimistic number. HAI labels name the process, not the component. The 0.909 vs 0.864 process-Top-1 gap is 1 attack out of 22 (exact sign test p=1.00, not distinguishable from chance) — HAI is real evidence of detection, not of localization skill. The 0.077 baseline isn't an unfair comparison either: tuning its threshold properly only reaches 0.091, still far below our 0.428 (real HAI channels have near-zero clean-period variance, so the per-node breach rule alarms almost regardless of threshold).

---

# Results: real protocol (LIVE)

- Modbus TCP read against our own emulated plant
- 30 seeded attacks, real protocol, real timing
- Detection F1 0.951, 0 false alarms/h
- Origin Top-1 0.833, Top-3 0.867
- Read latency: p95 2.4 ms

Notes: Not physical hardware — plant_emulator/ runs our simulator physics behind a real Modbus TCP server. The backend's live-ingestion code is read-only, enforced by a unit test; a separate attacker module is the only writer. Source: reports/live_metrics.json.

---

# Limitations

- Simulator is our own model
- HAI recall is 0.276
- LIVE mode is a real protocol, not a real plant
- One attack at a time evaluated
- Top-1 isolation click wrong 8 of 48
- HAI needs one labelled tuning day

Notes: Results on the simulator do not predict a real plant. LIVE mode proves the protocol path and masking logic work, not that the model generalises to physical hardware. We state this plainly in the documentation. Concurrent attacks are future work.

---

# Why it matters

- Localization is the output, not a by-product
- One pipeline: simulator, real data, real protocol
- Laptop CPU: 1.1 ms median step
- Reproducible: `python -m eval.run`, `python -m eval.live`
- Next: multi-attack and physical-hardware validation

Notes: The 1.1 ms is median time per 2 Hz step on an Intel Core Ultra 7 255H with the final models. Edge hardware was not tested.
