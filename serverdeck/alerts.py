"""Small, dependency-free state-change alerts for the terminal dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import ServerSnapshot, ServerStatus

Severity = Literal["information", "warning", "error"]


@dataclass(frozen=True, slots=True)
class AlertEvent:
    severity: Severity
    title: str
    message: str


def detect_alerts(
    previous: ServerSnapshot | None, current: ServerSnapshot
) -> list[AlertEvent]:
    """Return notifications for meaningful transitions only.

    The first sample is intentionally quiet (checking -> online/offline), so
    opening the dashboard does not produce a burst of notifications.
    """

    if previous is None or previous.status is ServerStatus.CHECKING:
        return []
    if previous.status == current.status and not (previous.metrics and current.metrics):
        return []

    alerts: list[AlertEvent] = []
    name = current.server.name
    if previous.status != current.status:
        if current.status is ServerStatus.OFFLINE:
            alerts.append(
                AlertEvent(
                    "error",
                    "server offline",
                    f"{name} is offline: {current.error or 'no response'}",
                )
            )
        elif current.status is ServerStatus.DEGRADED:
            alerts.append(
                AlertEvent(
                    "warning",
                    "server degraded",
                    f"{name} is degraded: {', '.join(current.issues) or 'health check failed'}",
                )
            )
        elif previous.status is ServerStatus.OFFLINE:
            alerts.append(
                AlertEvent(
                    "information",
                    "server recovered",
                    f"{name} is back online",
                )
            )
        else:
            alerts.append(
                AlertEvent("information", "server online", f"{name} is online")
            )

    if previous.metrics and current.metrics:
        old_states = {
            service.name: service.state for service in previous.metrics.services
        }
        new_states = {
            service.name: service.state for service in current.metrics.services
        }
        failed = [
            service
            for service, state in new_states.items()
            if old_states.get(service) == "active" and state in {"inactive", "failed"}
        ]
        recovered = [
            service
            for service, state in new_states.items()
            if old_states.get(service) in {"inactive", "failed"} and state == "active"
        ]
        if failed:
            alerts.append(
                AlertEvent(
                    "warning",
                    "service down",
                    f"{name}: {', '.join(failed)} stopped",
                )
            )
        if recovered:
            alerts.append(
                AlertEvent(
                    "information",
                    "service recovered",
                    f"{name}: {', '.join(recovered)} is running",
                )
            )
    return alerts
