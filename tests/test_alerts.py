from __future__ import annotations

from dataclasses import replace

from serverdeck.alerts import detect_alerts
from serverdeck.demo import DEMO_CONFIG, DemoMonitor
from serverdeck.models import ServerStatus, ServiceState
from serverdeck.monitor import initial_snapshot


def demo_snapshot(server_id: str):
    server = next(s for s in DEMO_CONFIG.servers if s.id == server_id)
    return DemoMonitor().collect(server, initial_snapshot(server))


def test_first_offline_sample_is_quiet():
    server = DEMO_CONFIG.servers[0]
    current = replace(
        initial_snapshot(server),
        status=ServerStatus.OFFLINE,
        error="connection refused",
    )
    assert detect_alerts(initial_snapshot(server), current) == []


def test_offline_and_recovery_alerts():
    current = demo_snapshot("web-01")
    offline = replace(current, status=ServerStatus.OFFLINE, error="timed out")
    alerts = detect_alerts(current, offline)
    assert [alert.severity for alert in alerts] == ["error"]
    assert "offline" in alerts[0].message

    recovered = detect_alerts(offline, current)
    assert [alert.severity for alert in recovered] == ["information"]
    assert "back online" in recovered[0].message


def test_repeated_offline_does_not_spam():
    current = demo_snapshot("web-01")
    offline = replace(current, status=ServerStatus.OFFLINE, error="timed out")
    assert detect_alerts(offline, offline) == []


def test_service_failure_alert():
    previous = demo_snapshot("web-01")
    assert previous.metrics is not None
    metrics = replace(
        previous.metrics,
        services=(
            ServiceState("nginx", "failed"),
            ServiceState("docker", "active"),
        ),
    )
    current = replace(
        previous,
        status=ServerStatus.DEGRADED,
        metrics=metrics,
        issues=("nginx failed",),
    )
    alerts = detect_alerts(previous, current)
    assert any(alert.title == "service down" for alert in alerts)
    assert any("nginx" in alert.message for alert in alerts)
