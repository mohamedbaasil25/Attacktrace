# Judge Q&A preparation

Numbers are from `reports/metrics.json` unless a file or command is named.

**Disclosure:** the demo uses the scenarios with the strongest measured reliability; aggregate
numbers cover all scenarios.

**1. Why three signals instead of one?**
Each signal fails alone. Deviation ties a spoofed sensor with its own PLC, onset is noisy at 0.5 s resolution, and causal rank ignores magnitude. Combined with a tie rule, Top-1 rose from 0.66 to 0.88 on the same 50-attack protocol as the final test set. We call this an **iterative tuning win, not a held-out result**, and volunteer why rather than wait to be asked: the tie rule's logic (earliest onset, then downstream reachability, then node-type order) was designed by a person observing specific failures on that 50-attack set and adjusting the rule until they resolved, then fixing it as deterministic code. That's a human-in-the-loop dependency on the exact set later reported as the headline number — closer to tuning than to a clean train/test split, distinct from grid-tuning the signal weights (which used a separate 400-419 tuning split). The final, independently-measured held-out Top-1 is 0.84.

**2. What if several components are attacked at once?**
We did not evaluate that. All 50 held-out attacks are single-origin, and the tool ranks one origin. Behaviour with concurrent origins is untested, so we do not claim it.

**3. Can it run at the edge?**
Not tested on edge hardware. On a laptop (Intel Core Ultra 7 255H, CPU, 4 threads) one 0.5 s step took a median 1.1 ms and p95 2.3 ms (measured with the final models). Model files are 6.6 KB (graph attention) and 120 KB (MLP).

**4. Does it generalise to other plants?**
Partly shown. The same code ran on the simulator (9 nodes) and on HAI (50 features), but HAI needed a labelled tuning day for thresholds. A new plant needs clean training data and one labelled day; we have tested two plants, not more.

**5. What is the false-alarm rate?**
Simulator: 0.0 per hour on 20 clean 5-minute runs (100 minutes). HAI: 0.18 per hour on `test1`. The baseline gives 3.6 per hour on the simulator.

**6. How is this different from an ordinary anomaly detector?**
An anomaly detector says "something is wrong". AttackTrace's output is the origin, the confidence, the path and an action. On the same simulator data the baseline anomaly detector names the right origin 68% of the time (Top-1) against our 84%.

**7. Simulator versus real data: which numbers should we trust?**
Both, for different claims. Simulator numbers (F1 0.904, Top-1 0.84) test the method on a plant we built, so they are optimistic. HAI is real data and is weaker: strict F1 0.428, recall 0.276, 22 of 28 attacks detected.

**8. Why is HAI recall so low?**
Most HAI attacks are slow, and clean-train thresholds do not transfer across recording days. The mean delay on detected attacks is 143 s. Point-adjusted F1 is 0.915, but we report strict F1 0.428 as the honest figure.

**9. Does the origin on HAI mean the right component?**
No. HAI labels name the attacked process (P1–P3), so we score process-level Top-1: 0.714 overall and 0.909 on detected attacks. Always answering "P1" scores 0.864 on detected attacks, a gain of 1 attack out of 22 — an exact sign test puts that at p = 1.00, not distinguishable from chance. We treat HAI as real evidence of *detection*, not of component- or process-level localization skill.

**9a. Is the 0.077 HAI baseline an unfair comparison — was its threshold ever tuned?**
We checked: tuning the baseline's own 3-sigma threshold on `test2` (same procedure as our own detector threshold, swept wide) picks sigma≈50, not the shipped 3, and only raises its held-out strict F1 from 0.077 to 0.091 — still far below our 0.428. The reason: one or two real HAI channels have near-zero clean-period variance, so the per-node breach rule alarms on nearly every sample from sigma=3 through roughly sigma=500 regardless of any attack. That's a structural limit of a per-node-OR baseline on real sensor data, not an untuned number we left unfavorable on purpose.

**10. How reliable is the confidence number?**
At the earlier calibration, mean top-1 confidence was 0.87 against 0.88 accuracy. We recalibrated afterwards (temperature 0.062) and did not re-measure that pair as its own figure. Sensor-versus-PLC near-ties show as close confidences on purpose.

**11. Which attack is hardest?**
Slow `sensor_ramp`: detection F1 0.673, Top-1 0.5, and 1 of 10 runs undetected. A ramp keeps the sensor consistent with the plant, so forecast error stays small. The origin was still in the top 3 for all `sensor_ramp` runs.

**12. Can the result be reproduced?**
Yes. Training is seeded and deterministic; `python -m eval.run` regenerated `reports/metrics.json` byte-identical in our final check (17.7 s with trained models). The Linux container differs in the last digits (23.7 s vs 23.3 s time-to-localize).

**13. What if the top origin is wrong?**
The Ambiguous gate flags close calls and shows the top 3 (Top-3 is 1.00 on the held-out attacks), but its tuning-set performance (0.952) does not transfer to the test set (0.864) — it catches only 2 of the 8 wrong Top-1 answers (25%). We're explicit that "not flagged" is not a safety signal: 6 of 8 wrong answers on the test set were never flagged. If the operator isolates a wrong node it does not contain (0 of 48 in the eval); the UI reads Not contained after 30 s and offers the next candidate. In the eval the Top-1 isolate click contained 40 of 48.

**14. Is the demo app itself secure?**
The write endpoints (attack, isolate, reset, mode) need an API key, the attack endpoint is limited to 10 per minute, and demo mode off returns 403. The key is part of the browser build, so this deters misuse of an exposed demo; it is not user authentication. Read-only endpoints and the live stream are open, and an empty key leaves writes open for local development.

**15. You said LIVE mode. Is that a real plant?**
No. It is a real protocol — Modbus TCP, the wire protocol industrial sensors and PLCs actually use — read against `plant_emulator/`, which runs the same simulator physics behind a Modbus server. We have not tested against physical hardware. We say this everywhere the mode appears: the README, the source pill in the UI, and the documentation.

**16. If it's read-only, how does the attack button work in LIVE mode?**
Through a separate code path. `backend/app/live/` (the connector, quality tracker, and engine) only ever issues Modbus read calls — a test scans its source for write calls and fails the build if one appears. The attack button calls a different package, `attacker/`, which is the only code allowed to write, and only to hosts on an allowlist (loopback, the Docker Compose host, or an explicit list). An operator in a real deployment would not wire that allowlist to a production PLC.

**17. How did LIVE mode perform against the real metrics?**
On 30 seeded attacks over the real protocol: detection F1 0.951 (recall 0.906, 0 false alarms/h), Top-1 0.833, Top-3 0.867, mean time to localize 8.1 s, Modbus read latency p95 2.4 ms. Top-1 is close to the simulator's 0.84; Top-3 is lower (0.867 vs 1.00) because of `sensor_ramp`, the same scenario that is hardest on the simulator (Q11). Source: `reports/live_metrics.json`.

**18. What happens if the emulator drops out mid-run?**
Tested directly (`python -m eval.live_faults`): killing the emulator makes the source report `down` with no exception and no false origin; a simulated slow network turns the affected tag's quality to `stale`; a corrupted out-of-range reading is excluded from the origin ranking rather than reported as the attack's source. All three passed. A 60-minute soak run (`reports/live_soak.json`) with two forced reconnects and 5 attacks over the hour checked the same thing over a longer window: 0 exceptions, both reconnects recovered in 3.5 s, and memory fell rather than grew (350 MB to 87 MB; no leak).

