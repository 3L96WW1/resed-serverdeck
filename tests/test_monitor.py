from __future__ import annotations

from pathlib import Path

from serverdeck.config import Config, ServerConfig, Settings
from serverdeck.models import ServerStatus
from serverdeck.monitor import Monitor


def test_disabled_server_is_offline_without_probe(tmp_path: Path):
    server = ServerConfig(
        id="puzzlebox",
        name="puzzlebox",
        transport="ssh",
        host="192.0.2.222",
        user="nobody",
        enabled=False,
    )
    config = Config(
        path=tmp_path / "serverdeck.yaml",
        settings=Settings(history=False),
        servers=(server,),
    )
    monitor = Monitor(config)
    seen = []
    try:
        snapshots = monitor.collect_all(
            [server], {}, lambda snapshot: seen.append(snapshot)
        )
    finally:
        monitor.close()

    snapshot = snapshots["puzzlebox"]
    assert snapshot.status is ServerStatus.OFFLINE
    assert snapshot.error == "monitoring disabled (placeholder)"
    assert seen == [snapshot]
