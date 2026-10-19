# Submission checklist (Sustainathon 2026, AI-07)

Status as of Phase 11. Open items are listed below.

| # | Requirement | Status | Satisfied by |
|---|---|---|---|
| 1 | Selected one problem statement (AI-07 Attack-Localization) | ✅ | `README.md` (title line) |
| 2 | Defined the problem | ✅ | `submission/AttackTrace_Documentation.md` §1 |
| 3 | Explained the approach | ✅ | `submission/AttackTrace_Documentation.md` §2–§3; short form in `README.md` |
| 4 | Innovation / novelty | ✅ | `submission/AttackTrace_Documentation.md` §6 (`QA_Prep.md` adds judge answers in Part 4) |
| 5 | Functional prototype | ✅ | `backend/`, `frontend/`, `docker-compose.yml`, `plant_emulator/`, `attacker/`; verified in Phase 13: pytest 237 passed, vitest 127 passed, Playwright 6 passed with the demo key enforced, `submission/evidence/` |
| 6 | Documentation and presentation | ✅ | `README.md` ✅; `submission/AttackTrace_Documentation.md` ✅; `submission/AttackTrace_Slides.md` ✅ |
| 7 | Demonstration ready | ✅ | Prototype and 19 screenshots ✅ (`submission/screenshots/`, `submission/evidence/rehearsal.md`); `submission/Demo_Script.md` ✅, `submission/QA_Prep.md` ✅ |
| 8 | External APIs, datasets and libraries disclosed | ✅ | `submission/THIRD_PARTY.md` |

## Open items
- **Project licence:** MIT, `LICENSE`. Copyright holder: TechWizards.
- **HAI licence:** the source states CC BY-SA 4.0 and CC BY 4.0. Recorded as ambiguous in `submission/THIRD_PARTY.md`. The dataset is not in the zip.
- **Demo key:** `.env.example` ships a placeholder `AT_API_KEY` / `VITE_API_KEY`. Change before exposing the demo; the key is in the browser build (deterrent only).
- **Google Fonts:** the UI loads two fonts over the network. Disclosed in `THIRD_PARTY.md`.
- **LIVE mode:** a real Modbus TCP read against the project's own emulated plant (`plant_emulator/`), not physical hardware. Read-only by test (`test_the_live_package_has_no_write_path`); the only writer is the separate `attacker/` package. Results in `reports/live_metrics.json`, `reports/live_faults.json`, `reports/live_soak.json`. Docker clean-start with `plant-emulator` in the stack verified: both services healthy, LIVE mode reaches `calibrating`, `reports/metrics.json` unchanged.
