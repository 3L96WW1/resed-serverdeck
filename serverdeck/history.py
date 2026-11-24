"""A tiny SQLite history store for availability and sparkline continuity."""

from __future__ import annotations

import contextlib
import sqlite3
import time
from pathlib import Path

from .models import ServerSnapshot

SAMPLE_INTERVAL_SECONDS = 30


class HistoryStore:
    """Keep a small rolling history without turning ServerDeck into a TSDB.

    One row is written for each host at most every 30 seconds.  The detail panel
    uses the rows for a 24-hour availability figure, and the last CPU points
    are reused for the sparkline after a restart.
    """

    def __init__(self, path: Path, retention_days: int = 7) -> None:
        self.path = path
        self.retention_days = retention_days
        self._last_sample: dict[str, float] = {}
        self._last_prune: float = 0.0
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path, timeout=5)
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    server_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    status TEXT NOT NULL,
                    cpu REAL,
                    memory REAL,
                    disk REAL,
                    load REAL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS samples_server_ts "
                "ON samples (server_id, ts)"
            )
            self._connection.commit()
            self.prune()
        except Exception:
            self.close()
            raise

    def record(self, snapshot: ServerSnapshot, *, now: float | None = None) -> bool:
        """Record a sample if this host's previous sample is old enough."""

        now = now if now is not None else snapshot.checked_at.timestamp()
        previous = self._last_sample.get(snapshot.server.id, 0.0)
        if now - previous < SAMPLE_INTERVAL_SECONDS:
            return False
        metrics = snapshot.metrics
        self._connection.execute(
            """
            INSERT INTO samples
                (server_id, ts, status, cpu, memory, disk, load)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.server.id,
                now,
                snapshot.status.value,
                metrics.cpu_percent if metrics else None,
                metrics.memory_percent if metrics else None,
                metrics.disk_percent if metrics else None,
                metrics.load1 if metrics else None,
            ),
        )
        self._last_sample[snapshot.server.id] = now
        if now - self._last_prune >= 3600:
            self.prune(now=now)
        self._connection.commit()
        return True

    def availability(self, server_id: str, hours: int = 24) -> float | None:
        since = time.time() - hours * 3600
        row = self._connection.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN status IN ('online', 'degraded') THEN 1 ELSE 0 END)
            FROM samples
            WHERE server_id = ? AND ts >= ?
            """,
            (server_id, since),
        ).fetchone()
        total = int(row[0] or 0)
        if total == 0:
            return None
        reachable = int(row[1] or 0)
        return 100.0 * reachable / total

    def recent_cpu(self, server_id: str, limit: int) -> tuple[float, ...]:
        rows = self._connection.execute(
            """
            SELECT cpu FROM samples
            WHERE server_id = ? AND cpu IS NOT NULL
            ORDER BY ts DESC LIMIT ?
            """,
            (server_id, max(1, limit)),
        ).fetchall()
        return tuple(float(row[0]) for row in reversed(rows))

    def prune(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        cutoff = now - self.retention_days * 86400
        self._connection.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        self._connection.commit()
        self._last_prune = now

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.close()
            self._connection = None
