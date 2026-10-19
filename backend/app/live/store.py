"""SQLite persistence for LIVE incidents (standard library). Incidents survive a restart; raw tag
history does not (only the engine's own 5-minute ring buffer exists)."""

import json
import sqlite3
from pathlib import Path

from app.schemas import Incident

FINAL = {"closed", "contained"}


class IncidentStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                detected_at REAL NOT NULL,
                status TEXT NOT NULL,
                origin TEXT NOT NULL,   -- ranking with score breakdown (JSON)
                path TEXT NOT NULL,     -- propagation path (JSON)
                payload TEXT NOT NULL   -- the full incident (JSON)
            )"""
        )
        self._db.commit()

    def save(self, inc: Incident) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                inc.id,
                inc.mode,
                inc.detected_at,
                inc.status,
                json.dumps([o.model_dump() for o in inc.origin]),
                json.dumps([p.model_dump() for p in inc.path]),
                inc.model_dump_json(),
            ),
        )
        self._db.commit()

    def load(self, mode: str = "live") -> list[Incident]:
        """Stored incidents of one mode, oldest first. One that was still running when the process
        stopped is reported as closed: nothing was watching it."""
        rows = self._db.execute(
            "SELECT payload FROM incidents WHERE mode = ? ORDER BY detected_at, id", (mode,)
        ).fetchall()
        out = []
        for (payload,) in rows:
            inc = Incident.model_validate_json(payload)
            if inc.status not in FINAL:
                inc.status = "closed"
            out.append(inc)
        return out

    def close(self) -> None:
        self._db.close()
