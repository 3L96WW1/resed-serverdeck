"""Value objects shared by collectors, the monitor, and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .config import ServerConfig, Thresholds


class ServerStatus(str, Enum):
    CHECKING = "checking"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class ServiceState:
    name: str
    state: str

    @property
    def running(self) -> bool:
        return self.state == "active"

    @property
    def known(self) -> bool:
        return self.state not in {"unknown", "unavailable", ""}


@dataclass(frozen=True, slots=True)
class HostMetrics:
    hostname: str
    os_name: str
    kernel: str
    arch: str
    uptime_seconds: float
    cpu_count: int
    cpu_percent: float
    load1: float
    load5: float
    load15: float
    memory_total: int
    memory_used: int
    swap_total: int
    swap_used: int
    disk_total: int
    disk_used: int
    process_count: int
    net_rx_total: int
    net_tx_total: int
    services: tuple[ServiceState, ...] = ()
    sampled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def memory_percent(self) -> float:
        if self.memory_total <= 0:
            return 0.0
        return min(100.0, 100.0 * self.memory_used / self.memory_total)

    @property
    def swap_percent(self) -> float:
        if self.swap_total <= 0:
            return 0.0
        return min(100.0, 100.0 * self.swap_used / self.swap_total)

    @property
    def disk_percent(self) -> float:
        if self.disk_total <= 0:
            return 0.0
        return min(100.0, 100.0 * self.disk_used / self.disk_total)

    @property
    def load_per_core(self) -> float:
        return self.load1 / max(1, self.cpu_count)


@dataclass(frozen=True, slots=True)
class ServerSnapshot:
    server: ServerConfig
    status: ServerStatus
    checked_at: datetime
    metrics: HostMetrics | None = None
    error: str | None = None
    issues: tuple[str, ...] = ()
    poll_ms: float | None = None
    cpu_history: tuple[float, ...] = ()
    rx_rate: float | None = None
    tx_rate: float | None = None
    last_online: datetime | None = None

    @property
    def hostname(self) -> str:
        return self.metrics.hostname if self.metrics else self.server.name

    @property
    def is_up(self) -> bool:
        return self.status in {ServerStatus.ONLINE, ServerStatus.DEGRADED}


def determine_status(
    metrics: HostMetrics, thresholds: Thresholds
) -> tuple[ServerStatus, tuple[str, ...]]:
    """Return connectivity/health status plus human-readable reasons."""

    issues: list[str] = []
    if metrics.cpu_percent >= thresholds.cpu:
        issues.append(f"CPU {metrics.cpu_percent:.0f}%")
    if metrics.memory_percent >= thresholds.memory:
        issues.append(f"memory {metrics.memory_percent:.0f}%")
    if metrics.disk_percent >= thresholds.disk:
        issues.append(f"disk {metrics.disk_percent:.0f}%")
    if metrics.load_per_core >= thresholds.load_per_core:
        issues.append(f"load {metrics.load1:.2f}")

    for service in metrics.services:
        if service.known and not service.running:
            issues.append(f"{service.name} {service.state}")

    return (ServerStatus.DEGRADED if issues else ServerStatus.ONLINE, tuple(issues))


def human_bytes(value: float, *, per_second: bool = False) -> str:
    suffix = "/s" if per_second else ""
    if value < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{amount:.0f} B{suffix}"
            return f"{amount:.1f} {unit}{suffix}"
        amount /= 1024
    return f"{amount:.1f} PB{suffix}"


def human_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def relative_time(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "never"
    current = now or datetime.now(timezone.utc)
    seconds = max(0, int((current - when).total_seconds()))
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def snapshot_to_dict(snapshot: ServerSnapshot) -> dict[str, object]:
    metrics = snapshot.metrics
    payload: dict[str, object] = {
        "id": snapshot.server.id,
        "name": snapshot.server.name,
        "group": snapshot.server.group,
        "transport": snapshot.server.transport,
        "endpoint": snapshot.server.endpoint,
        "status": snapshot.status.value,
        "checked_at": snapshot.checked_at.isoformat(),
        "poll_ms": round(snapshot.poll_ms, 1) if snapshot.poll_ms is not None else None,
        "error": snapshot.error,
        "issues": list(snapshot.issues),
    }
    if metrics is not None:
        payload["metrics"] = {
            "hostname": metrics.hostname,
            "os": metrics.os_name,
            "kernel": metrics.kernel,
            "arch": metrics.arch,
            "uptime_seconds": round(metrics.uptime_seconds, 1),
            "cpu_count": metrics.cpu_count,
            "cpu_percent": round(metrics.cpu_percent, 1),
            "load": [
                round(metrics.load1, 2),
                round(metrics.load5, 2),
                round(metrics.load15, 2),
            ],
            "memory_total_bytes": metrics.memory_total,
            "memory_used_bytes": metrics.memory_used,
            "memory_percent": round(metrics.memory_percent, 1),
            "swap_total_bytes": metrics.swap_total,
            "swap_used_bytes": metrics.swap_used,
            "disk_total_bytes": metrics.disk_total,
            "disk_used_bytes": metrics.disk_used,
            "disk_percent": round(metrics.disk_percent, 1),
            "process_count": metrics.process_count,
            "net_rx_total_bytes": metrics.net_rx_total,
            "net_tx_total_bytes": metrics.net_tx_total,
            "net_rx_rate_bytes": (
                round(snapshot.rx_rate, 1) if snapshot.rx_rate is not None else None
            ),
            "net_tx_rate_bytes": (
                round(snapshot.tx_rate, 1) if snapshot.tx_rate is not None else None
            ),
            "services": [
                {"name": service.name, "state": service.state}
                for service in metrics.services
            ],
        }
    return payload
