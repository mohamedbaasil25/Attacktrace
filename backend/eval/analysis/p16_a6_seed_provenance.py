"""Phase 16 A6: seed provenance for the "Top-1 0.66 -> 0.88" figure.

Evidence-only finding: CLAUDE.md's own record of this change ("Tie-break rule (post Phase 6)")
describes it as a HELD-OUT comparison -- "Held-out localization now Top-1 0.88/Top-3 1.00 (was
0.66/1.00)" -- not a tuning-set comparison. No commit history, script, or doc in this repo records
the exact seed numbers used for the "before" (0.66) measurement specifically (git history for this
project was reset earlier and no longer has that granularity). This script does not invent a seed
range; it reports what IS and ISN'T recoverable, and flags a methodology point the fix-prompt's own
framing (item 17: "label ... as tuning data") does not match the available evidence for.
"""

from eval.analysis._util import merge_write_final
from eval.localization import TEST_ATTACK_SEEDS, TUNE_ATTACK_SEEDS


def analyze() -> dict[str, object]:
    return {
        "claude_md_record": (
            "## Tie-break rule (post Phase 6) ... Held-out localization now Top-1 0.88 / Top-3 "
            "1.00 (was 0.66 / 1.00): offset 1.0, freeze 1.0, actuator 1.0, rogue setpoint 0.9, "
            "ramp 0.5."
        ),
        "current_test_seeds": {
            "range": list(TEST_ATTACK_SEEDS),
            "per_scenario": True,
            "n_scenarios": 5,
            "n_total": 50,
        },
        "current_tuning_seeds": {"range": list(TUNE_ATTACK_SEEDS), "per_scenario": True},
        "finding": (
            "CLAUDE.md explicitly labels the 0.66->0.88 comparison as 'held-out', using the same "
            "word it uses elsewhere for the final test set (seeds 1000-1009). No record in this "
            "repo (CLAUDE.md, eval scripts, or git history -- history was reset earlier in this "
            "project and no longer has per-commit granularity back to Phase 6) specifies a "
            "DIFFERENT seed range for the 'before' (0.66) run. The fix-prompt's item 17 "
            "instruction to 'label the figure as tuning data, name the seeds' assumes it IS "
            "tuning data; that "
            "assumption is not supported by what's recoverable here."
        ),
        "distinct_but_real_caveat": (
            "Separately from the tuning-data question: the tie-break RULE ITSELF (earliest onset, "
            "then downstream reachability, then node-type ordering) was designed by a human "
            "observing failures on a held-out set, then encoded as fixed logic -- not grid-tuned "
            "like the weights. Iterating rule design against the same set later reported as the "
            "headline number is a standard, real risk of held-out evaluation (repeated "
            "human-in-the-loop decisions informed by the test set), distinct from but related to "
            "classic train/tune-on-test leakage. This is worth stating in the document as a "
            "methodology caveat regardless of whether the exact seeds match."
        ),
        "resolution": (
            "RESOLVED, final (owner first delegated the call to the implementer, who chose "
            "'held-out + caveat'; owner then explicitly overrode that choice and directed "
            "the stronger framing below -- this supersedes the earlier resolution). A second "
            "doc was found during the first resolution pass: `submission/QA_Prep.md` had "
            "explicitly called this an 'earlier tuning set', contradicting CLAUDE.md's "
            "'Held-out (50 attacks)' label. Final decision: label the figure an **iterative "
            "tuning win, not a held-out result** -- the tie-break rule's own logic (earliest "
            "onset, then downstream reachability, then node-type order) was designed by a "
            "person observing specific failures on that 50-attack set and iterating the rule "
            "until they resolved, then fixing it as deterministic code. That human-in-the-loop "
            "dependency on the exact set later reported as the headline number is "
            "methodologically closer to tuning than to a clean train/test split, even though "
            "the data range is the same one used for the final held-out number. This is a "
            "deliberately more conservative claim than CLAUDE.md's own 'held-out' label; the "
            "final, independently-measured held-out Top-1 (0.84, seeds 1000-1009) is "
            "unaffected and remains the number to cite for actual generalization. Updated: "
            "submission/AttackTrace_Documentation.md (x2), submission/AttackTrace_Slides.md, "
            "submission/QA_Prep.md, docs/Pitch_Deck_Outline_Phase5.3.md."
        ),
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("seed_provenance_0p66_0p88", result)
    print(f"wrote {out}: RESOLVED, final -- iterative tuning win, not held-out; applied to 5 docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
