"""Phase 14 Part A: evidence and diagnosis scripts, run against existing eval outputs.

Each module exposes `analyze() -> dict` (pure, no side effects) and a `main()` that merges its
result into `reports/fix_analysis.json` under its own top-level key, read-modify-write, so modules
can be run independently or all together via `python -m eval.analysis.run_all`.
"""
