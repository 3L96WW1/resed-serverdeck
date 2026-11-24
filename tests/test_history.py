from __future__ import annotations

import time
from dataclasses import replace

from serverdeck.demo import DEMO_CONFIG, DemoMonitor
from serverdeck.history import HistoryStore
from serverdeck.models import ServerStatus
from serverdeck.render import detail_text
from serverdeck.themes import PALETTES


def make_snapshot(server_id: str, status: ServerStatus | None = None):
    server = next(server for server in DEMO_CONFIG.servers if server.id == server_id)
    snapshot = DemoMonitor().collect(server, None)
    if status is not None:
        snapshot = replace(snapshot, status=status)
    return snapshot


def test_history_records_samples_and_calculates_availability(tmp_path):
    store = HistoryStore(tmp_path / "history.db", retention_days=7)
    start = time.time()
    online = make_snapshot("web-01", ServerStatus.ONLINE)
    offline = replace(make_snapshot("web-01", ServerStatus.OFFLINE), metrics=None)
    assert store.record(online, now=start) is True
    assert store.record(online, now=start + 10) is False
    assert store.record(offline, now=start + 31) is True
    assert store.availability("web-01", 24) == 50.0
    assert store.recent_cpu("web-01", 10) == (online.metrics.cpu_percent,)
    store.close()


def test_history_is_per_server_and_survives_reopen(tmp_path):
    path = tmp_path / "history.db"
    start = time.time()
    store = HistoryStore(path)
    store.record(make_snapshot("web-01", ServerStatus.ONLINE), now=start)
    store.record(make_snapshot("db-01", ServerStatus.OFFLINE), now=start)
    store.close()

    reopened = HistoryStore(path)
    assert reopened.availability("web-01", 24) == 100.0
    assert reopened.availability("db-01", 24) == 0.0
    reopened.close()


def test_availability_line_in_detail():
    snapshot = make_snapshot("web-01", ServerStatus.ONLINE)
    rendered = detail_text(
        snapshot,
        DEMO_CONFIG.settings.thresholds,
        PALETTES["mono"],
        availability_24h=99.4,
    )
    assert "AVAIL" in rendered.plain
    assert "99.4% · 24h" in rendered.plain
