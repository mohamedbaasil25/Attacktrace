"""Per-tag data quality: is the value fit to score? good | stale | missing | out_of_range | frozen

`stale`, `missing` and `out_of_range` mean the data cannot be trusted, so those tags are kept out of
the origin ranking (a data fault is not an attack). `frozen` is advisory only: a reading that stops
changing is exactly what a `sensor_freeze` attack looks like, so it must never hide a tag from
detection or ranking.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Quality = Literal["good", "stale", "missing", "out_of_range", "frozen"]

EXCLUDED: frozenset[str] = frozenset({"stale", "missing", "out_of_range"})
ADVISORY: frozenset[str] = frozenset({"frozen"})
RANGE_MARGIN = 0.05  # fraction of the span allowed beyond min/max before `out_of_range`


def excluded_from_ranking(q: Quality) -> bool:
    return q in EXCLUDED


@dataclass(frozen=True)
class TagSpec:
    lo: float
    hi: float
    sensor: bool  # only sensors carry noise, so only they can be `frozen`


@dataclass
class _Track:
    value: float | None = None
    changed_ts: float | None = None  # when the value last differed from the previous one
    seen_ts: float | None = None


class QualityTracker:
    def __init__(
        self,
        specs: Mapping[str, TagSpec],
        stale_after_s: float,
        max_age_s: float,
        frozen_after_s: float,
    ) -> None:
        self.specs = dict(specs)
        self.stale_after_s, self.max_age_s, self.frozen_after_s = (
            stale_after_s,
            max_age_s,
            frozen_after_s,
        )
        self._t: dict[str, _Track] = {t: _Track() for t in self.specs}

    def observe(self, tag: str, value: float, ts: float) -> None:
        tr = self._t[tag]
        if tr.value is None or value != tr.value:
            tr.changed_ts = ts
        tr.value, tr.seen_ts = value, ts

    def reset(self) -> None:
        self._t = {t: _Track() for t in self.specs}

    def classify(self, tag: str, now: float) -> Quality:
        tr, spec = self._t[tag], self.specs[tag]
        if tr.value is None or tr.seen_ts is None:
            return "missing"
        age = now - tr.seen_ts
        if age > self.max_age_s:
            return "missing"
        if age > self.stale_after_s:
            return "stale"
        margin = RANGE_MARGIN * (spec.hi - spec.lo)
        if not math.isfinite(tr.value) or not spec.lo - margin <= tr.value <= spec.hi + margin:
            return "out_of_range"
        if spec.sensor and self._frozen(tag, now):
            return "frozen"
        return "good"

    def classify_all(self, now: float) -> dict[str, Quality]:
        return {t: self.classify(t, now) for t in self.specs}

    def _frozen(self, tag: str, now: float) -> bool:
        """Identical for `frozen_after_s` while at least one other tag changed in that window."""
        tr = self._t[tag]
        if tr.changed_ts is None or now - tr.changed_ts < self.frozen_after_s:
            return False
        return any(
            o.changed_ts is not None and now - o.changed_ts < self.frozen_after_s
            for name, o in self._t.items()
            if name != tag
        )
