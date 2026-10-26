"""Tag-level historian (Production Transition Roadmap, Phase 2 MVP): raw per-node samples across
every mode, independent of incident snapshots. The engine itself only keeps a 5-minute in-memory
ring buffer (`frontend/src/store/live.ts`'s `RING_CAPACITY`); this is what survives longer than
that -- forensics, audit, and future retraining data. SQLite, same shape as `app/evidence.py`'s
`IncidentStore`.
"""

import sqlite3
import time
from pathlib import Path
from typing import NamedTuple

from app.schemas import LiveMessage


class HistorySample(NamedTuple):
    t: float
    value: float
    score: float
    status: str


class HistoryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS samples (
                t REAL NOT NULL,
                mode TEXT NOT NULL,
                node_id TEXT NOT NULL,
                value REAL NOT NULL,
                score REAL NOT NULL,
                status TEXT NOT NULL
            )"""
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_samples_node_t ON samples(node_id, t)")
        self._db.commit()

    def record(self, msg: LiveMessage) -> None:
        rows = [(msg.t, msg.mode, n.id, n.value, n.score, n.status) for n in msg.nodes]
        if not rows:
            return
        self._db.executemany(
            "INSERT INTO samples (t, mode, node_id, value, score, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._db.commit()

    def query(
        self, node_id: str, since: float | None = None, until: float | None = None
    ) -> list[HistorySample]:
        clauses = ["node_id = ?"]
        params: list[object] = [node_id]
        if since is not None:
            clauses.append("t >= ?")
            params.append(since)
        if until is not None:
            clauses.append("t <= ?")
            params.append(until)
        sql = (
            f"SELECT t, value, score, status FROM samples WHERE {' AND '.join(clauses)} ORDER BY t"
        )
        return [HistorySample(*row) for row in self._db.execute(sql, params).fetchall()]

    def prune(self, retention_s: float, now: float | None = None) -> int:
        """Deletes samples older than `retention_s`; returns how many. Cheap enough to call on
        every write, but the caller (the WS tick loop) throttles it since this does a full
        table scan without a `t`-only index."""
        cutoff = (now if now is not None else time.time()) - retention_s
        cur = self._db.execute("DELETE FROM samples WHERE t < ?", (cutoff,))
        self._db.commit()
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
