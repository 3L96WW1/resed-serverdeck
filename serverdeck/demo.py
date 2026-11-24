"""Built-in fake fleet used by ``serverdeck --demo`` and UI screenshots."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config, ServerConfig, Settings, Thresholds
from .models import HostMetrics, ServerSnapshot, ServiceState
from .monitor import MonitorBase


@dataclass(frozen=True, slots=True)
class DemoProfile:
    hostname: str
    os_name: str
    kernel: str
    cpu_count: int
    cpu: float
    memory_percent: float
    memory_gib: int
    disk_percent: float
    disk_gib: int
    processes: int
    load: float
    uptime_days: float
    rx_mbps: float
    tx_mbps: float
    services: tuple[tuple[str, str], ...]
    offline: bool = False
    error: str = ""


DEMO_SERVERS: tuple[ServerConfig, ...] = (
    ServerConfig(
        id="atlas",
        name="atlas",
        transport="local",
        group="Default Server Group",
        tags=("local", "core"),
        services=("ssh", "docker"),
    ),
    ServerConfig(
        id="web-01",
        name="web-01",
        transport="ssh",
        host="10.0.10.21",
        port=22,
        user="ops",
        group="Production Web",
        tags=("prod", "web"),
        services=("nginx", "docker"),
    ),
    ServerConfig(
        id="db-01",
        name="db-01",
        transport="ssh",
        host="10.0.10.31",
        port=22,
        user="ops",
        group="Data Services",
        tags=("prod", "database"),
        services=("postgresql", "pgbackrest"),
    ),
    ServerConfig(
        id="edge-sg",
        name="edge-sg",
        transport="ssh",
        host="103.85.24.10",
        port=2222,
        user="edge",
        group="Edge Network",
        tags=("edge", "sin"),
        services=("caddy", "wireguard"),
    ),
    ServerConfig(
        id="build-02",
        name="build-02",
        transport="ssh",
        host="10.0.20.14",
        port=22,
        user="ci",
        group="CI / Build",
        tags=("ci", "ephemeral"),
        services=("docker", "gitlab-runner"),
    ),
    ServerConfig(
        id="cache-01",
        name="cache-01",
        transport="ssh",
        host="10.0.10.41",
        port=22,
        user="ops",
        group="Caching",
        tags=("prod", "cache"),
        services=("redis",),
    ),
    ServerConfig(
        id="api-01",
        name="api-01",
        transport="ssh",
        host="10.0.10.22",
        port=22,
        user="ops",
        group="Production Web",
        tags=("prod", "api"),
        services=("nginx", "puma"),
    ),
    ServerConfig(
        id="api-02",
        name="api-02",
        transport="ssh",
        host="10.0.10.23",
        port=22,
        user="ops",
        group="Production Web",
        tags=("prod", "api"),
        services=("nginx", "puma"),
    ),
    ServerConfig(
        id="worker-01",
        name="worker-01",
        transport="ssh",
        host="10.0.30.11",
        port=22,
        user="jobs",
        group="Background Jobs",
        tags=("prod", "worker"),
        services=("worker", "redis"),
    ),
    ServerConfig(
        id="monitor-01",
        name="monitor-01",
        transport="ssh",
        host="10.0.30.21",
        port=22,
        user="ops",
        group="Operations",
        tags=("ops", "monitoring"),
        services=("prometheus", "grafana"),
    ),
    ServerConfig(
        id="backup-01",
        name="backup-01",
        transport="ssh",
        host="10.0.40.11",
        port=22,
        user="backup",
        group="Storage",
        tags=("storage", "backup"),
        services=("borgmatic", "smbd"),
    ),
    ServerConfig(
        id="gateway-eu",
        name="gateway-eu",
        transport="ssh",
        host="51.24.18.77",
        port=2222,
        user="edge",
        group="Edge Network",
        tags=("edge", "eu"),
        services=("caddy", "wireguard"),
    ),
    ServerConfig(
        id="cache-02",
        name="cache-02",
        transport="ssh",
        host="10.0.10.42",
        port=22,
        user="ops",
        group="Caching",
        tags=("prod", "cache"),
        services=("redis",),
    ),
    ServerConfig(
        id="search-01",
        name="search-01",
        transport="ssh",
        host="10.0.10.32",
        port=22,
        user="ops",
        group="Data Services",
        tags=("prod", "search"),
        services=("opensearch",),
    ),
    ServerConfig(
        id="staging-01",
        name="staging-01",
        transport="ssh",
        host="10.0.50.11",
        port=22,
        user="deploy",
        group="Staging",
        tags=("staging", "web"),
        services=("nginx", "docker"),
    ),
    ServerConfig(
        id="build-03",
        name="build-03",
        transport="ssh",
        host="10.0.20.15",
        port=22,
        user="ci",
        group="CI / Build",
        tags=("ci", "ephemeral"),
        services=("docker", "gitlab-runner"),
    ),
)

DEMO_PROFILES: dict[str, DemoProfile] = {
    "atlas": DemoProfile(
        hostname="atlas",
        os_name="Debian GNU/Linux 13 (trixie)",
        kernel="6.12.16-amd64",
        cpu_count=16,
        cpu=22,
        memory_percent=38,
        memory_gib=64,
        disk_percent=54,
        disk_gib=1024,
        processes=412,
        load=1.1,
        uptime_days=23.4,
        rx_mbps=0.5,
        tx_mbps=0.2,
        services=(("ssh", "active"), ("docker", "active")),
    ),
    "web-01": DemoProfile(
        hostname="web-01",
        os_name="Ubuntu 24.04.3 LTS",
        kernel="6.8.0-88-generic",
        cpu_count=8,
        cpu=57,
        memory_percent=63,
        memory_gib=32,
        disk_percent=41,
        disk_gib=240,
        processes=286,
        load=2.3,
        uptime_days=62.8,
        rx_mbps=18.4,
        tx_mbps=7.6,
        services=(("nginx", "active"), ("docker", "active")),
    ),
    "db-01": DemoProfile(
        hostname="db-01",
        os_name="Rocky Linux 9.6 (Blue Onyx)",
        kernel="5.14.0-570.el9.x86_64",
        cpu_count=16,
        cpu=34,
        memory_percent=91,
        memory_gib=64,
        disk_percent=73,
        disk_gib=2048,
        processes=508,
        load=2.0,
        uptime_days=118.2,
        rx_mbps=5.2,
        tx_mbps=11.8,
        services=(("postgresql", "active"), ("pgbackrest", "active")),
    ),
    "edge-sg": DemoProfile(
        hostname="edge-sg",
        os_name="Alpine Linux v3.21",
        kernel="6.12.8-lts",
        cpu_count=4,
        cpu=41,
        memory_percent=46,
        memory_gib=8,
        disk_percent=28,
        disk_gib=80,
        processes=149,
        load=1.5,
        uptime_days=191.6,
        rx_mbps=34.1,
        tx_mbps=29.3,
        services=(("caddy", "active"), ("wireguard", "active")),
    ),
    "build-02": DemoProfile(
        hostname="build-02",
        os_name="Debian GNU/Linux 13 (trixie)",
        kernel="6.12.16-amd64",
        cpu_count=32,
        cpu=93,
        memory_percent=72,
        memory_gib=128,
        disk_percent=81,
        disk_gib=4096,
        processes=967,
        load=26.4,
        uptime_days=7.1,
        rx_mbps=12.7,
        tx_mbps=3.1,
        services=(("docker", "active"), ("gitlab-runner", "active")),
    ),
    "cache-01": DemoProfile(
        hostname="cache-01",
        os_name="Ubuntu 22.04.5 LTS",
        kernel="5.15.0-139-generic",
        cpu_count=4,
        cpu=8,
        memory_percent=35,
        memory_gib=16,
        disk_percent=12,
        disk_gib=100,
        processes=92,
        load=0.3,
        uptime_days=143.4,
        rx_mbps=0,
        tx_mbps=0,
        services=(("redis", "active"),),
        offline=True,
        error="connect to 10.0.10.41 port 22: Connection timed out",
    ),
    "api-01": DemoProfile(
        hostname="api-01",
        os_name="Ubuntu 24.04.3 LTS",
        kernel="6.8.0-88-generic",
        cpu_count=8,
        cpu=61,
        memory_percent=54,
        memory_gib=32,
        disk_percent=38,
        disk_gib=240,
        processes=303,
        load=3.1,
        uptime_days=41.2,
        rx_mbps=12.5,
        tx_mbps=8.2,
        services=(("nginx", "active"), ("puma", "active")),
    ),
    "api-02": DemoProfile(
        hostname="api-02",
        os_name="Debian GNU/Linux 13 (trixie)",
        kernel="6.12.16-amd64",
        cpu_count=8,
        cpu=47,
        memory_percent=58,
        memory_gib=32,
        disk_percent=35,
        disk_gib=240,
        processes=311,
        load=2.4,
        uptime_days=56.7,
        rx_mbps=11.3,
        tx_mbps=6.7,
        services=(("nginx", "active"), ("puma", "active")),
    ),
    "worker-01": DemoProfile(
        hostname="worker-01",
        os_name="Ubuntu 22.04.5 LTS",
        kernel="5.15.0-139-generic",
        cpu_count=16,
        cpu=67,
        memory_percent=66,
        memory_gib=64,
        disk_percent=58,
        disk_gib=512,
        processes=455,
        load=10.4,
        uptime_days=22.5,
        rx_mbps=5.1,
        tx_mbps=2.3,
        services=(("worker", "active"), ("redis", "active")),
    ),
    "monitor-01": DemoProfile(
        hostname="monitor-01",
        os_name="Debian GNU/Linux 12 (bookworm)",
        kernel="6.1.0-38-amd64",
        cpu_count=4,
        cpu=17,
        memory_percent=33,
        memory_gib=16,
        disk_percent=24,
        disk_gib=120,
        processes=162,
        load=0.55,
        uptime_days=206.0,
        rx_mbps=1.2,
        tx_mbps=0.8,
        services=(("prometheus", "active"), ("grafana", "active")),
    ),
    "backup-01": DemoProfile(
        hostname="backup-01",
        os_name="Rocky Linux 9.6 (Blue Onyx)",
        kernel="5.14.0-570.el9.x86_64",
        cpu_count=8,
        cpu=12,
        memory_percent=51,
        memory_gib=32,
        disk_percent=68,
        disk_gib=4096,
        processes=203,
        load=0.4,
        uptime_days=301.2,
        rx_mbps=0,
        tx_mbps=0,
        services=(("borgmatic", "active"), ("smbd", "active")),
        offline=True,
        error="connect to 10.0.40.11 port 22: No route to host",
    ),
    "gateway-eu": DemoProfile(
        hostname="gateway-eu",
        os_name="Alpine Linux v3.21",
        kernel="6.12.8-lts",
        cpu_count=4,
        cpu=33,
        memory_percent=41,
        memory_gib=8,
        disk_percent=19,
        disk_gib=80,
        processes=128,
        load=0.85,
        uptime_days=152.0,
        rx_mbps=44.0,
        tx_mbps=39.0,
        services=(("caddy", "active"), ("wireguard", "active")),
    ),
    "cache-02": DemoProfile(
        hostname="cache-02",
        os_name="Ubuntu 24.04.3 LTS",
        kernel="6.8.0-88-generic",
        cpu_count=8,
        cpu=14,
        memory_percent=61,
        memory_gib=32,
        disk_percent=18,
        disk_gib=200,
        processes=188,
        load=0.7,
        uptime_days=68.0,
        rx_mbps=24.0,
        tx_mbps=21.0,
        services=(("redis", "active"),),
    ),
    "search-01": DemoProfile(
        hostname="search-01",
        os_name="Ubuntu 22.04.5 LTS",
        kernel="5.15.0-139-generic",
        cpu_count=16,
        cpu=68,
        memory_percent=88,
        memory_gib=64,
        disk_percent=62,
        disk_gib=1024,
        processes=390,
        load=11.2,
        uptime_days=35.0,
        rx_mbps=7.4,
        tx_mbps=4.2,
        services=(("opensearch", "active"),),
    ),
    "staging-01": DemoProfile(
        hostname="staging-01",
        os_name="Debian GNU/Linux 12 (bookworm)",
        kernel="6.1.0-38-amd64",
        cpu_count=8,
        cpu=23,
        memory_percent=47,
        memory_gib=32,
        disk_percent=33,
        disk_gib=240,
        processes=250,
        load=0.85,
        uptime_days=12.0,
        rx_mbps=2.1,
        tx_mbps=0.9,
        services=(("nginx", "active"), ("docker", "active")),
    ),
    "build-03": DemoProfile(
        hostname="build-03",
        os_name="Debian GNU/Linux 12 (bookworm)",
        kernel="6.1.0-38-amd64",
        cpu_count=32,
        cpu=94,
        memory_percent=76,
        memory_gib=128,
        disk_percent=84,
        disk_gib=4096,
        processes=840,
        load=29.1,
        uptime_days=5.3,
        rx_mbps=9.8,
        tx_mbps=2.6,
        services=(("docker", "active"), ("gitlab-runner", "active")),
    ),
}

DEMO_CONFIG = Config(
    path=Path("<demo>"),
    settings=Settings(
        refresh_interval=2.0,
        connect_timeout=3.0,
        command_timeout=5.0,
        thresholds=Thresholds(cpu=80, memory=85, disk=90, load_per_core=1.0),
        history=False,
    ),
    servers=DEMO_SERVERS,
)


class DemoMonitor(MonitorBase):
    """Generates smooth, deterministic-ish sample data for previews."""

    def __init__(self) -> None:
        super().__init__(DEMO_CONFIG.settings)

    def collect(
        self, server: ServerConfig, previous: ServerSnapshot | None
    ) -> ServerSnapshot:
        profile = DEMO_PROFILES[server.id]
        now = datetime.now(timezone.utc)
        if profile.offline:
            snapshot = self._offline(server, previous, profile.error)
            if snapshot.last_online is None:
                snapshot = replace(
                    snapshot, last_online=now - timedelta(minutes=12, seconds=37)
                )
            return snapshot

        elapsed = 2.0
        if previous and previous.metrics:
            elapsed = max(
                0.2,
                min(30.0, (now - previous.metrics.sampled_at).total_seconds()),
            )
        phase = time.monotonic() / 9 + int.from_bytes(server.id.encode(), "little") % 17
        jitter = random.Random(f"{server.id}:{int(time.monotonic() // 2)}")
        cpu = _clamp(profile.cpu + math.sin(phase) * 5.5 + jitter.uniform(-3.0, 3.0))
        memory = _clamp(
            profile.memory_percent
            + math.sin(phase / 3.7) * 1.8
            + jitter.uniform(-0.7, 0.7)
        )
        disk = _clamp(profile.disk_percent + jitter.uniform(-0.2, 0.2))
        load = max(
            0.01,
            profile.load
            + (cpu - profile.cpu) / 100 * profile.cpu_count * 0.6
            + jitter.uniform(-0.1, 0.1),
        )

        rx_base = profile.rx_mbps * 1024 * 1024
        tx_base = profile.tx_mbps * 1024 * 1024
        rx_rate = max(0, rx_base * (1 + jitter.uniform(-0.22, 0.22)))
        tx_rate = max(0, tx_base * (1 + jitter.uniform(-0.22, 0.22)))

        total_mem = profile.memory_gib * 1024**3
        total_disk = profile.disk_gib * 1024**3
        uptime = profile.uptime_days * 86400
        total_rx = rx_base * 86400
        total_tx = tx_base * 86400
        if previous and previous.metrics:
            elapsed_int = max(1.0, elapsed)
            uptime = previous.metrics.uptime_seconds + elapsed
            total_rx = previous.metrics.net_rx_total + int(rx_rate * elapsed_int)
            total_tx = previous.metrics.net_tx_total + int(tx_rate * elapsed_int)

        metrics = HostMetrics(
            hostname=profile.hostname,
            os_name=profile.os_name,
            kernel=profile.kernel,
            arch="x86_64",
            uptime_seconds=uptime,
            cpu_count=profile.cpu_count,
            cpu_percent=cpu,
            load1=load,
            load5=max(0.01, load * 0.92 + jitter.uniform(-0.1, 0.1)),
            load15=max(0.01, load * 0.84 + jitter.uniform(-0.1, 0.1)),
            memory_total=total_mem,
            memory_used=int(total_mem * memory / 100),
            swap_total=8 * 1024**3 if profile.memory_gib >= 32 else 0,
            swap_used=0,
            disk_total=total_disk,
            disk_used=int(total_disk * disk / 100),
            process_count=profile.processes + jitter.randint(-8, 8),
            net_rx_total=total_rx,
            net_tx_total=total_tx,
            services=tuple(
                ServiceState(name=name, state=state) for name, state in profile.services
            ),
            sampled_at=now,
        )
        return self._finalize(
            server,
            metrics,
            poll_ms=jitter.uniform(28, 76),
            previous=previous,
        )


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
