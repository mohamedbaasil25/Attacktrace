"""Timestamp handling: put per-tag samples onto the engine's 500 ms tick.

A sample carries its source timestamp when the protocol has one, else the receive time (Modbus
has none). The engine asks for the value of every tag "as of now": the newest sample not newer
than `now` and not older than `max_age_s` (last-value-hold). A sample older than the newest one
already accepted for its tag is dropped and counted; a repeat of the same timestamp is ignored.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    value: float
    ts: float  # seconds, any consistent clock (wall clock in LIVE)


class Aligner:
    def __init__(self, tags: Iterable[str], max_age_s: float, history: int = 8) -> None:
        self.max_age_s = max_age_s
        self._hist: dict[str, deque[Sample]] = {t: deque(maxlen=history) for t in tags}
        self.dropped_out_of_order = 0
        self.duplicates = 0
        self.accepted = 0

    def add(self, tag: str, value: float, ts: float) -> bool:
        """Store a sample; False when it is dropped (older than the newest) or a repeat."""
        hist = self._hist[tag]
        if hist:
            newest = hist[-1].ts
            if ts < newest:
                self.dropped_out_of_order += 1
                return False
            if ts == newest:
                self.duplicates += 1
                return False
        hist.append(Sample(value, ts))
        self.accepted += 1
        return True

    def last(self, tag: str) -> Sample | None:
        hist = self._hist[tag]
        return hist[-1] if hist else None

    def at(self, tag: str, t: float) -> Sample | None:
        """Newest sample with ts <= t, if it is no older than max_age_s; else None."""
        for s in reversed(self._hist[tag]):
            if s.ts <= t:
                return s if t - s.ts <= self.max_age_s else None
        return None

    def clear(self) -> None:
        for h in self._hist.values():
            h.clear()
        self.dropped_out_of_order = self.duplicates = self.accepted = 0
