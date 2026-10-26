"""Phase 16 A7: confidence-gate transfer table (target 0.95 vs achieved), tuning vs test.

Pure arithmetic over the already-committed `metrics.json.ambiguity` block -- no new run. No
separate "validation" split for the gate was ever saved (only "tuning", n=140, and the top-level
test, n=50); reported as Not measured rather than invented.
"""

import json
from typing import Any

from eval.analysis._util import merge_write_final, reports_dir


def _wrong_top1_flagged(block: dict[str, Any]) -> dict[str, object]:
    n = int(block["n_incidents"])
    top1_rate = None  # overall top1 isn't stored in the ambiguity block itself; derive below
    n_ambig = int(block["n_ambiguous"])
    n_non = int(block["n_non_ambiguous"])
    top1_non = float(block["top1_non_ambiguous"])
    top1_ambig = float(block["top1_ambiguous"])
    correct_non = round(top1_non * n_non)
    correct_ambig = round(top1_ambig * n_ambig)
    total_correct = correct_non + correct_ambig
    total_wrong = n - total_correct
    wrong_in_ambig = n_ambig - correct_ambig  # wrong-top1 cases that WERE flagged
    return {
        "n_incidents": n,
        "n_ambiguous": n_ambig,
        "n_non_ambiguous": n_non,
        "top1_overall_derived": total_correct / n,
        "total_wrong_top1": total_wrong,
        "wrong_top1_flagged_ambiguous": wrong_in_ambig,
        "fraction_of_wrong_top1_flagged": wrong_in_ambig / total_wrong if total_wrong else None,
        "top1_rate_unused": top1_rate,
    }


def analyze() -> dict[str, object]:
    m: dict[str, Any] = json.loads((reports_dir() / "metrics.json").read_text())
    amb = m["ambiguity"]
    gate_margin = amb["gate_margin"]

    test_row = _wrong_top1_flagged(amb)
    tuning_row = _wrong_top1_flagged(amb["tuning"])

    return {
        "gate_margin_target": 0.95,
        "gate_margin_value": gate_margin,
        "table": {
            "tuning": {
                "ambiguous_rate": amb["tuning"]["ambiguous_rate"],
                "top1_non_ambiguous": amb["tuning"]["top1_non_ambiguous"],
                **tuning_row,
                "target_met": amb["tuning"]["top1_non_ambiguous"] >= 0.95,
            },
            "validation": "Not measured: no separate validation-split ambiguity run was saved "
            "(only 'tuning', n=140, and the top-level test set, n=50, exist in metrics.json).",
            "test": {
                "ambiguous_rate": amb["ambiguous_rate"],
                "top1_non_ambiguous": amb["top1_non_ambiguous"],
                **test_row,
                "target_met": amb["top1_non_ambiguous"] >= 0.95,
            },
        },
        "headline": (
            f"Gate target (Top-1 on non-ambiguous incidents >= 0.95) was reached on the TUNING "
            f"set it was calibrated on ({amb['tuning']['top1_non_ambiguous']:.3f}) but NOT on the "
            f"held-out test set ({amb['top1_non_ambiguous']:.3f}, {test_row['total_wrong_top1']} "
            f"wrong Top-1 of 50, only {test_row['wrong_top1_flagged_ambiguous']} of them flagged "
            f"ambiguous = {test_row['fraction_of_wrong_top1_flagged']:.0%} caught). The gate did "
            "not transfer from tuning to test."
        ),
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("gate_transfer", result)
    print(f"wrote {out}: {result['headline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
