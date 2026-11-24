"""Collection orchestration and snapshot history."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .collectors import CollectionError, make_collector
from .config import Config, ServerConfig, Settings
from .models import (
    HostMetrics,
    ServerSnapshot,
    ServerStatus,
    determine_status,
)

SnapshotCallback = Callable[[ServerSnapshot], None]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def initial_snapshot(server: ServerConfig) -> ServerSnapshot:
    return ServerSnapshot(
        server=server,
        status=ServerStatus.CHECKING,
        checked_at=utcnow(),
    )


class MonitorBase:
    """Shared snapshot/rate/history logic for live and demo monitors."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(
        self, server: ServerConfig, previous: ServerSnapshot | None
    ) -> ServerSnapshot:
        raise NotImplementedError

    def _finalize(
        self,
        server: ServerConfig,
        metrics: HostMetrics,
        poll_ms: float,
        previous: ServerSnapshot | None,
    ) -> ServerSnapshot:
        status, issues = determine_status(metrics, self.settings.thresholds)
        rx_rate, tx_rate = self._network_rates(previous, metrics)
        history = list(previous.cpu_history if previous else ())
        history.append(metrics.cpu_percent)
        history = history[-self.settings.history_points :]
        return ServerSnapshot(
            server=server,
            status=status,
            checked_at=metrics.sampled_at,
            metrics=metrics,
            issues=issues,
            poll_ms=poll_ms,
            cpu_history=tuple(history),
            rx_rate=rx_rate,
            tx_rate=tx_rate,
            last_online=metrics.sampled_at,
        )

    def _offline(
        self,
        server: ServerConfig,
        previous: ServerSnapshot | None,
        error: str,
    ) -> ServerSnapshot:
        now = utcnow()
        last_online = previous.last_online if previous else None
        return ServerSnapshot(
            server=server,
            status=ServerStatus.OFFLINE,
            checked_at=now,
            error=error,
            cpu_history=previous.cpu_history if previous else (),
            last_online=last_online,
        )

    @staticmethod
    def _network_rates(
        previous: ServerSnapshot | None, current: HostMetrics
    ) -> tuple[float | None, float | None]:
        if previous is None or previous.metrics is None:
            return None, None
        elapsed = (current.sampled_at - previous.metrics.sampled_at).total_seconds()
        if elapsed <= 0.05:
            return None, None
        delta_rx = current.net_rx_total - previous.metrics.net_rx_total
        delta_tx = current.net_tx_total - previous.metrics.net_tx_total
        if delta_rx < 0 or delta_tx < 0:
            # Counters reset, e.g. after a reboot.
            return None, None
        return delta_rx / elapsed, delta_tx / elapsed

    def collect_all(
        self,
        servers: tuple[ServerConfig, ...] | list[ServerConfig],
        previous: dict[str, ServerSnapshot],
        callback: SnapshotCallback,
    ) -> dict[str, ServerSnapshot]:
        """Collect hosts concurrently and call ``callback`` as each finishes."""

        results: dict[str, ServerSnapshot] = {}
        if not servers:
            return results
        workers = min(8, len(servers))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="serverdeck-collect"
        ) as pool:
            futures: dict[Future[ServerSnapshot], ServerConfig] = {}
            for server in servers:
                try:
                    future = pool.submit(self.collect, server, previous.get(server.id))
                except Exception as exc:
                    snapshot = self._offline(
                        server,
                        previous.get(server.id),
                        f"{type(exc).__name__}: {exc}",
                    )
                    results[server.id] = snapshot
                    callback(snapshot)
                    continue
                futures[future] = server

            for future in as_completed(futures):
                server = futures[future]
                try:
                    snapshot = future.result()
                except CollectionError as exc:
                    snapshot = self._offline(server, previous.get(server.id), str(exc))
                except Exception as exc:
                    snapshot = self._offline(
                        server,
                        previous.get(server.id),
                        f"unexpected collector error: {type(exc).__name__}: {exc}",
                    )
                results[server.id] = snapshot
                callback(snapshot)
        return results

    def close(self) -> None:
        return None


class Monitor(MonitorBase):
    """Live monitor: local shell or persistent SSH connections."""

    def __init__(self, config: Config) -> None:
        super().__init__(config.settings)
        self.config = config
        self._collectors = {
            server.id: make_collector(server, config.settings)
            for server in config.servers
        }

    def collect(
        self, server: ServerConfig, previous: ServerSnapshot | None
    ) -> ServerSnapshot:
        collector = self._collectors[server.id]
        try:
            collection = collector.collect()
        except CollectionError as exc:
            return self._offline(server, previous, str(exc))
        except Exception as exc:
            return self._offline(
                server,
                previous,
                f"unexpected collector error: {type(exc).__name__}: {exc}",
            )
        return self._finalize(server, collection.metrics, collection.poll_ms, previous)

    def close(self) -> None:
        for collector in self._collectors.values():
            with contextlib.suppress(Exception):
                collector.close()
