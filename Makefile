# AttackTrace — run from repo root. Override PY if your venv lives elsewhere.
ifeq ($(OS),Windows_NT)
PY ?= backend/.venv/Scripts/python
BOOT ?= py -3.11
else
PY ?= backend/.venv/bin/python
BOOT ?= python3.11
endif
BE := cd backend &&
FE := cd frontend &&
PYB := $(abspath $(PY))

.PHONY: setup dev test lint eval up package emulator live-train eval-live live-soak demo preflight demo-trials

setup:
	$(BE) $(BOOT) -m venv .venv && $(PYB) -m pip install -e ".[dev]"
	$(FE) npm ci

dev:
	$(BE) $(PYB) -m uvicorn app.main:app --reload --port 8000 & $(FE) npm run dev

test:
	$(BE) $(PYB) -m pytest -q
	$(FE) npm test

lint:
	$(BE) $(PYB) -m ruff check . ../plant_emulator ../attacker && $(PYB) -m ruff format --check . ../plant_emulator ../attacker && $(PYB) -m mypy --strict app eval ../plant_emulator && $(PYB) -m mypy --strict ../attacker
	$(FE) npm run lint && npm run typecheck

eval:
	$(BE) $(PYB) -m eval.run

up:
	docker compose up --build

package:
	$(PYB) submission/tools/package.py

emulator:
	$(PYB) -m plant_emulator

# Needs the emulator running (make emulator). Records AT_LIVE_TRAIN_MIN minutes of clean live traffic.
live-train:
	$(BE) $(PYB) -m app.live.train

# Phase 13 Part F: needs the emulator running (make emulator) and a trained LIVE model
# (make live-train). Real time: about 2.75 h with the defaults. Writes reports/live_metrics.json.
eval-live:
	$(BE) $(PYB) -m eval.live

# Spawns and kills its own emulator subprocess; do not run `make emulator` first. Real time:
# about 1 h with the defaults. Writes reports/live_soak.json.
live-soak:
	$(BE) $(PYB) -m eval.live_soak

# Phase 14 C1: 30 fresh trials per demo click-path, SIM (fast) and LIVE (needs the emulator
# running + a trained LIVE model; real time, ~8-9 h for the LIVE half). Writes
# reports/demo_trials.json + .md.
demo-trials:
	$(BE) $(PYB) -m eval.demo_trials

# Phase 14 C2: start the stack, wait healthy, reset, warm up, print READY and the measured
# click path (from reports/demo_trials.json if it exists).
demo:
	$(PYB) scripts/demo.py

# Phase 14 C2: <=30s pre-demo checks (backend health, WS rate, frontend, key, console errors,
# emulator). Run this right after `make demo` says READY.
preflight:
	$(PYB) scripts/preflight.py
