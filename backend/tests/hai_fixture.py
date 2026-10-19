"""A tiny synthetic dataset in the HAI file layout, so tests never depend on the real download."""

import gzip
from pathlib import Path

import numpy as np

FEATURES = ["P1_A", "P1_B", "P1_C", "P2_D", "P3_E", "P4_F"]
CONSTANT = "P2_Auto"  # constant in training, must be dropped
TRAIN_ROWS, TEST1_ROWS, TEST2_ROWS = 4000, 3000, 2500
TEST1_ATTACK = (1500, 1700)  # offset on P1_A, flagged attack_P1
TEST2_ATTACK = (1200, 1400)  # offset on P2_D, flagged attack_P2


def _signals(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    a = np.sin(2 * np.pi * t / 200)
    return {
        "P1_A": a + 0.05 * rng.normal(size=n),
        "P1_B": 0.5 * np.roll(a, 3) + 0.05 * rng.normal(size=n),
        "P1_C": np.sin(2 * np.pi * t / 130) + 0.05 * rng.normal(size=n),
        "P2_D": np.sin(2 * np.pi * t / 300) + 0.05 * rng.normal(size=n),
        "P3_E": np.cos(2 * np.pi * t / 170) + 0.05 * rng.normal(size=n),
        "P4_F": 0.05 * rng.normal(size=n),
    }


def _write(
    path: Path, n: int, seed: int, attack: tuple[int, int] | None, column: str, flag: str
) -> None:
    sig = _signals(n, seed)
    lab = {
        "attack": np.zeros(n, int),
        "attack_P1": np.zeros(n, int),
        "attack_P2": np.zeros(n, int),
        "attack_P3": np.zeros(n, int),
    }
    if attack:
        s, e = attack
        sig[column][s:e] += 3.0
        lab["attack"][s:e] = 1
        lab[flag][s:e] = 1
    cols = {
        "time": [f"2020-01-01 00:{i // 60 % 60:02d}:{i % 60:02d}" for i in range(n)],
        **sig,
        CONSTANT: np.zeros(n),
        **lab,
    }
    lines = [";".join(cols)]
    for i in range(n):
        lines.append(
            ";".join(str(cols[c][i]) if c == "time" else f"{float(cols[c][i]):.6g}" for c in cols)
        )
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def make_dataset(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / "train1.csv.gz", TRAIN_ROWS, 1, None, "P1_A", "attack_P1")
    _write(folder / "test1.csv.gz", TEST1_ROWS, 2, TEST1_ATTACK, "P1_A", "attack_P1")
    _write(folder / "test2.csv.gz", TEST2_ROWS, 3, TEST2_ATTACK, "P2_D", "attack_P2")
    return folder
