"""Fraction of clean HAI samples (label 0, outside the 60 s post-attack ignore window) on which the
detector's alert is on, for the held-out file. `metrics.json` stores false alarms per hour but not
this per-sample rate; run from backend/:  python ../submission/tools/hai_clean_alert_rate.py"""
import json
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.data.hai import load_hai
from app.detect.hai_pipeline import load_hai_detector, split_tests
from eval.hai import score_file

s = get_settings()
data = load_hai(s.hai_dir)
_, held = split_tests(data)
loaded = load_hai_detector(s.models_dir)
out = {}
for f in held:
    sc = score_file(loaded, f)
    y = f.labels()
    clean = y == 0
    out[f.name] = {
        "clean_samples": int(clean.sum()),
        "clean_samples_alerting": int((sc.alert & clean).sum()),
        "clean_alert_rate": float((sc.alert & clean).sum() / clean.sum()),
        "attack_samples": int((y == 1).sum()),
        "attack_samples_alerting": int((sc.alert & (y == 1)).sum()),
    }
print(json.dumps(out, indent=1))
