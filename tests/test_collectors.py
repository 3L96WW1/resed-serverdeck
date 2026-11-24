from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import paramiko
import pytest

from serverdeck.collectors import (
    CollectionError,
    LocalCollector,
    SSHCollector,
    build_script,
    parse_probe,
)
from serverdeck.config import ServerConfig, Settings, Thresholds
from serverdeck.demo import DEMO_CONFIG, DemoMonitor
from serverdeck.models import (
    HostMetrics,
    ServerStatus,
    ServiceState,
    determine_status,
    human_bytes,
    human_uptime,
)
from serverdeck.monitor import MonitorBase, initial_snapshot


def probe_text(**overrides: str) -> str:
    values = {
        "hostname": "test-host",
        "os": "Debian GNU/Linux 13",
        "kernel": "6.12.0-test",
        "arch": "x86_64",
        "cpu_count": "4",
        "uptime_seconds": "12345.5",
        "load1": "0.50",
        "load5": "0.40",
        "load15": "0.30",
        "cpu_percent": "12.5",
        "memory_total_bytes": str(8 * 1024**3),
        "memory_used_bytes": str(2 * 1024**3),
        "swap_total_bytes": str(1024**3),
        "swap_used_bytes": str(128 * 1024**2),
        "disk_total_bytes": str(100 * 1024**3),
        "disk_used_bytes": str(40 * 1024**3),
        "process_count": "123",
        "net_rx_total_bytes": "1000000",
        "net_tx_total_bytes": "2000000",
    }
    values.update(overrides)
    lines = [f"{key}={value}" for key, value in values.items()]
    lines.extend(
        [
            "service.0.name=nginx",
            "service.0.state=active",
            "service.1.name=postgresql",
            "service.1.state=failed",
        ]
    )
    return "\n".join(lines) + "\n"


def test_parse_probe():
    metrics = parse_probe(probe_text())
    assert metrics.hostname == "test-host"
    assert metrics.cpu_count == 4
    assert metrics.cpu_percent == 12.5
    assert metrics.memory_percent == pytest.approx(25.0)
    assert metrics.disk_percent == pytest.approx(40.0)
    assert [service.state for service in metrics.services] == ["active", "failed"]


def test_parse_probe_rejects_missing_fields():
    with pytest.raises(CollectionError, match="incomplete data"):
        parse_probe("hostname=test\nos=Linux\n")


def test_parse_probe_rejects_bad_number():
    with pytest.raises(CollectionError, match="invalid number for load1"):
        parse_probe(probe_text(load1="not-a-number"))


def test_parse_probe_clamps_cpu():
    assert parse_probe(probe_text(cpu_percent="140")).cpu_percent == 100.0
    assert parse_probe(probe_text(cpu_percent="-5")).cpu_percent == 0.0


def test_local_collector_runs_probe():
    server = ServerConfig(id="local", name="local", transport="local")
    collection = LocalCollector(server, Settings(command_timeout=15)).collect()
    assert collection.metrics.hostname
    assert collection.metrics.cpu_count >= 1
    assert collection.metrics.memory_total > 0
    assert collection.poll_ms > 0


def test_build_script_quotes_service_names():
    script = build_script(["nginx", "weird;touch /tmp/nope"])
    assert "'weird;touch /tmp/nope'" in script
    # The quote keeps the metacharacter inside one shell word.
    result = subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "service.0.name=nginx" in result.stdout
    assert "service.1.name=weird;touch /tmp/nope" in result.stdout


def metric(
    *,
    cpu: float = 10,
    memory_used: int = 2 * 1024**3,
    memory_total: int = 8 * 1024**3,
    load: float = 0.2,
    services: tuple[ServiceState, ...] = (),
    sampled_at: datetime | None = None,
    rx: int = 1000,
    tx: int = 2000,
) -> HostMetrics:
    return HostMetrics(
        hostname="host",
        os_name="Linux",
        kernel="6.0",
        arch="x86_64",
        uptime_seconds=3600,
        cpu_count=4,
        cpu_percent=cpu,
        load1=load,
        load5=load,
        load15=load,
        memory_total=memory_total,
        memory_used=memory_used,
        swap_total=0,
        swap_used=0,
        disk_total=100 * 1024**3,
        disk_used=30 * 1024**3,
        process_count=100,
        net_rx_total=rx,
        net_tx_total=tx,
        services=services,
        sampled_at=sampled_at or datetime.now(UTC),
    )


def test_determine_status():
    status, issues = determine_status(metric(), Thresholds())
    assert status is ServerStatus.ONLINE
    assert issues == ()

    degraded, issues = determine_status(
        metric(
            cpu=90,
            memory_used=7 * 1024**3,
            load=6.0,
            services=(ServiceState("nginx", "failed"),),
        ),
        Thresholds(),
    )
    assert degraded is ServerStatus.DEGRADED
    assert "CPU 90%" in issues
    assert "memory 88%" in issues
    assert "load 6.00" in issues
    assert "nginx failed" in issues


class FinalizeMonitor(MonitorBase):
    def __init__(self) -> None:
        super().__init__(Settings(history_points=5, thresholds=Thresholds()))

    def collect(self, server, previous):
        raise NotImplementedError


def test_finalize_rates_history_and_last_online():
    monitor = FinalizeMonitor()
    server = ServerConfig(id="s", name="s", transport="local")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = monitor._finalize(
        server,
        metric(sampled_at=start, rx=1000, tx=2000),
        poll_ms=10,
        previous=None,
    )
    assert first.rx_rate is None
    assert first.cpu_history == (10,)
    second = monitor._finalize(
        server,
        metric(
            sampled_at=start + timedelta(seconds=2),
            rx=5000,
            tx=8000,
        ),
        poll_ms=20,
        previous=first,
    )
    assert second.rx_rate == pytest.approx(2000)
    assert second.tx_rate == pytest.approx(3000)
    assert second.cpu_history == (10, 10)
    assert second.last_online == start + timedelta(seconds=2)


def test_offline_preserves_history_and_last_online():
    monitor = FinalizeMonitor()
    server = ServerConfig(id="s", name="s", transport="local")
    now = datetime.now(UTC)
    previous = monitor._finalize(
        server, metric(sampled_at=now - timedelta(seconds=2)), 12, None
    )
    offline = monitor._offline(server, previous, "connection refused")
    assert offline.status is ServerStatus.OFFLINE
    assert offline.error == "connection refused"
    assert offline.cpu_history == previous.cpu_history
    assert offline.last_online == previous.last_online


def test_network_counter_reset_returns_no_rate():
    monitor = FinalizeMonitor()
    server = ServerConfig(id="s", name="s", transport="local")
    start = datetime.now(UTC)
    first = monitor._finalize(server, metric(sampled_at=start, rx=5000), 5, None)
    after_reboot = monitor._finalize(
        server,
        metric(sampled_at=start + timedelta(seconds=2), rx=100),
        5,
        first,
    )
    assert after_reboot.rx_rate is None


def test_demo_monitor_emits_all_states():
    monitor = DemoMonitor()
    states = {}
    monitor.collect_all(
        DEMO_CONFIG.servers,
        {server.id: initial_snapshot(server) for server in DEMO_CONFIG.servers},
        lambda snapshot: states.__setitem__(snapshot.server.id, snapshot),
    )
    assert states["cache-01"].status is ServerStatus.OFFLINE
    assert states["db-01"].status is ServerStatus.DEGRADED
    assert states["web-01"].status is ServerStatus.ONLINE
    assert all(
        snapshot.poll_ms is not None for snapshot in states.values() if snapshot.metrics
    )


def test_formatters():
    assert human_bytes(0) == "0 B"
    assert human_bytes(1024) == "1.0 KB"
    assert human_uptime(0) == "0m"
    assert human_uptime(3660) == "1h 01m"
    assert human_uptime(90000) == "1d 01h"


def _rsa_key() -> paramiko.RSAKey:
    return paramiko.RSAKey.generate(1024)


def test_tofu_known_hosts_merges_sequential_writes(tmp_path):
    known_hosts = tmp_path / "known_hosts"
    collector = SSHCollector(
        ServerConfig(
            id="s",
            name="s",
            transport="ssh",
            host="192.0.2.1",
            user="root",
            host_key_policy="tofu",
        ),
        Settings(known_hosts=known_hosts),
    )
    first = _rsa_key()
    second = _rsa_key()
    collector._persist_host_key([("host-a", "ssh-rsa", first)])
    collector._persist_host_key([("host-b", "ssh-rsa", second)])
    loaded = paramiko.HostKeys(str(known_hosts))
    assert loaded.lookup("host-a")["ssh-rsa"].asbytes() == first.asbytes()
    assert loaded.lookup("host-b")["ssh-rsa"].asbytes() == second.asbytes()
    assert (known_hosts.stat().st_mode & 0o077) == 0


def test_tofu_known_hosts_refuses_changed_key(tmp_path):
    known_hosts = tmp_path / "known_hosts"
    collector = SSHCollector(
        ServerConfig(
            id="s",
            name="s",
            transport="ssh",
            host="192.0.2.1",
            user="root",
            host_key_policy="tofu",
        ),
        Settings(known_hosts=known_hosts),
    )
    original = _rsa_key()
    collector._persist_host_key([("host-a", "ssh-rsa", original)])
    with pytest.raises(CollectionError, match="changed while connecting"):
        collector._persist_host_key([("host-a", "ssh-rsa", _rsa_key())])
    loaded = paramiko.HostKeys(str(known_hosts))
    assert loaded.lookup("host-a")["ssh-rsa"].asbytes() == original.asbytes()
