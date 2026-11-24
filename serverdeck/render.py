"""Rich renderables shared by the TUI and the one-shot CLI."""

from __future__ import annotations

import textwrap
from collections.abc import Iterable
from datetime import datetime

from rich.text import Text

from .config import Thresholds
from .models import (
    HostMetrics,
    ServerSnapshot,
    ServerStatus,
    human_uptime,
    relative_time,
)
from .themes import Palette

STATUS_ICON = {
    ServerStatus.ONLINE: "●",
    ServerStatus.DEGRADED: "◐",
    ServerStatus.OFFLINE: "●",
    ServerStatus.CHECKING: "○",
}


def _status_style(status: ServerStatus, palette: Palette) -> str:
    return {
        ServerStatus.ONLINE: f"bold {palette.online}",
        ServerStatus.DEGRADED: f"bold {palette.amber}",
        ServerStatus.OFFLINE: f"bold {palette.offline}",
        ServerStatus.CHECKING: palette.muted,
    }[status]


def status_badge(
    status: ServerStatus, palette: Palette, *, lowercase: bool = False
) -> Text:
    label = status.value if lowercase else status.value.upper()
    return Text(f"{STATUS_ICON[status]} {label}", style=_status_style(status, palette))


def metric_color(percent: float, threshold: float, palette: Palette) -> str:
    if percent >= threshold:
        return palette.red
    if percent >= threshold * 0.85:
        return palette.amber
    if percent >= 60:
        return palette.cyan
    return palette.green


def mini_gauge(
    percent: float, threshold: float, palette: Palette, width: int = 7
) -> Text:
    percent = max(0.0, min(100.0, percent))
    color = metric_color(percent, threshold, palette)
    filled = int(round(percent / 100 * width))
    filled = max(0, min(width, filled))
    result = Text()
    result.append("█" * filled, style=color)
    result.append("░" * (width - filled), style=palette.muted)
    result.append(f" {percent:>3.0f}%", style=color)
    return result


def load_cell(metrics: HostMetrics, thresholds: Thresholds, palette: Palette) -> Text:
    ratio = metrics.load_per_core
    if ratio >= thresholds.load_per_core:
        color = palette.red
    elif ratio >= thresholds.load_per_core * 0.85:
        color = palette.amber
    else:
        color = palette.cyan
    return Text(f"{metrics.load1:.2f}", style=color)


def compact_rate(value: float | None, *, suffix: bool = True) -> str:
    if value is None:
        return "—"
    amount = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if amount < 1024 or unit == "T":
            if unit == "B":
                return f"{amount:.0f}{unit}{'/s' if suffix else ''}"
            shown = f"{amount:.1f}" if amount < 10 else f"{amount:.0f}"
            return f"{shown}{unit}{'/s' if suffix else ''}"
        amount /= 1024
    return f"{amount:.1f}T/s"


def host_cell(snapshot: ServerSnapshot, palette: Palette) -> Text:
    name = snapshot.server.name
    cell = Text()
    cell.append(name, style=f"bold {palette.text}")
    if snapshot.server.transport == "local":
        cell.append("  local", style=palette.muted)
    elif snapshot.server.tags:
        cell.append(f"  {snapshot.server.tags[0]}", style=palette.muted)
    return cell


def table_cells(
    snapshot: ServerSnapshot,
    thresholds: Thresholds,
    palette: Palette,
    *,
    compact: bool = False,
) -> dict[str, Text]:
    metrics = snapshot.metrics
    dash = Text("—", style=palette.muted)
    cells: dict[str, Text] = {
        "host": host_cell(snapshot, palette),
        "status": status_badge(snapshot.status, palette, lowercase=True),
    }
    if metrics is None:
        for key in ("cpu", "mem", "disk", "load", "net", "uptime"):
            cells[key] = dash
        return cells

    gauge_width = 4 if compact else 6
    cells["cpu"] = mini_gauge(
        metrics.cpu_percent, thresholds.cpu, palette, width=gauge_width
    )
    cells["mem"] = mini_gauge(
        metrics.memory_percent, thresholds.memory, palette, width=gauge_width
    )
    cells["disk"] = mini_gauge(
        metrics.disk_percent, thresholds.disk, palette, width=gauge_width
    )
    cells["load"] = load_cell(metrics, thresholds, palette)
    rx = compact_rate(snapshot.rx_rate, suffix=False)
    tx = compact_rate(snapshot.tx_rate, suffix=False)
    net = Text()
    net.append("↓", style=palette.cyan)
    net.append(f" {rx}", style=palette.soft)
    net.append("  ↑", style=palette.green)
    net.append(f" {tx}", style=palette.soft)
    cells["net"] = net
    cells["uptime"] = Text(human_uptime(metrics.uptime_seconds), style=palette.soft)
    return cells


def summary_line(snapshots: Iterable[ServerSnapshot], palette: Palette) -> Text:
    """Render the header summary in neutral shades, not semantic status colors.

    The compact summary uses grayscale hierarchy only; bright green/red are
    reserved for the STATUS column and service states.
    """

    items = list(snapshots)
    counts = {
        status: sum(1 for item in items if item.status is status)
        for status in ServerStatus
    }
    summary_styles = {
        ServerStatus.ONLINE: palette.text,
        ServerStatus.DEGRADED: palette.soft,
        ServerStatus.OFFLINE: f"bold {palette.text}",
        ServerStatus.CHECKING: palette.muted,
    }
    text = Text()
    for index, status in enumerate(
        (
            ServerStatus.ONLINE,
            ServerStatus.DEGRADED,
            ServerStatus.OFFLINE,
            ServerStatus.CHECKING,
        )
    ):
        count = counts[status]
        if status is ServerStatus.CHECKING and count == 0:
            continue
        if index and text.plain:
            text.append("   ")
        style = summary_styles[status]
        text.append(STATUS_ICON[status] + " ", style=style)
        text.append(f"{count} {status.value}", style=style)
    text.append(f"   ·   {len(items)} hosts", style=palette.muted)
    return text


def _section(text: Text, title: str, palette: Palette, width: int = 33) -> None:
    label = title.upper() + " "
    text.append(label, style=f"bold {palette.accent}")
    text.append("─" * max(3, width - len(label)) + "\n", style=palette.border)


def _kv(
    text: Text, label: str, value: str, palette: Palette, value_style: str | None = None
) -> None:
    text.append(f"{label:<8}", style=palette.muted)
    text.append(value + "\n", style=value_style or palette.text)


def compact_bytes(value: float) -> str:
    if value < 0:
        return "—"
    amount = float(value)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if amount < 1024 or unit == "P":
            if unit == "B":
                return f"{amount:.0f}B"
            return f"{amount:.1f}{unit}" if amount < 100 else f"{amount:.0f}{unit}"
        amount /= 1024
    return f"{amount:.0f}P"


def _gauge_line(
    text: Text,
    label: str,
    percent: float,
    threshold: float,
    detail: str,
    palette: Palette,
    width: int = 8,
) -> None:
    percent = max(0.0, min(100.0, percent))
    color = metric_color(percent, threshold, palette)
    filled = max(0, min(width, int(round(percent / 100 * width))))
    text.append(f"{label:<5}", style=palette.muted)
    text.append("█" * filled, style=color)
    text.append("░" * (width - filled), style=palette.border)
    text.append(f" {percent:>3.0f}%", style=color)
    if detail:
        text.append(f"  {detail}\n", style=palette.soft)
    else:
        text.append("\n")


def _sparkline(
    values: Iterable[float], palette: Palette, width: int = 26, threshold: float = 80
) -> Text:
    chars = "▁▂▃▄▅▆▇█"
    points = list(values)[-width:]
    result = Text()
    if not points:
        result.append("collecting…", style=palette.muted)
        return result
    for value in points:
        value = max(0.0, min(100.0, value))
        char = chars[min(len(chars) - 1, int(value / 100 * len(chars)))]
        result.append(char, style=metric_color(value, threshold, palette))
    return result


def _service_line(name: str, state: str, palette: Palette) -> Text:
    text = Text()
    if state == "active":
        text.append("● ", style=palette.online)
        text.append(f"{name[:17]:<18}", style=palette.text)
        text.append("running", style=palette.online)
    elif state in {"inactive", "failed"}:
        text.append("○ ", style=palette.offline)
        text.append(f"{name[:17]:<18}", style=palette.text)
        text.append(state, style=palette.offline)
    elif state in {"activating", "deactivating", "reloading"}:
        text.append("◐ ", style=palette.amber)
        text.append(f"{name[:17]:<18}", style=palette.text)
        text.append(state, style=palette.amber)
    else:
        text.append("○ ", style=palette.muted)
        text.append(f"{name[:17]:<18}", style=palette.text)
        text.append(state or "unknown", style=palette.muted)
    return text


def _fit(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(0, width - 1)].rstrip() + "…"


def detail_text(
    snapshot: ServerSnapshot,
    thresholds: Thresholds,
    palette: Palette,
    *,
    availability_24h: float | None = None,
) -> Text:
    server = snapshot.server
    metrics = snapshot.metrics
    text = Text()

    text.append(server.name, style=f"bold {palette.text}")
    text.append("  ")
    text.append_text(status_badge(snapshot.status, palette))
    text.append("\n")
    text.append("GROUP  ", style=palette.muted)
    text.append(_fit(server.group, 26) + "\n", style=palette.soft)
    endpoint = server.endpoint
    if server.transport == "ssh" and server.user:
        endpoint = f"{server.user}@{server.host}:{server.port}"
    location = endpoint
    if server.tags:
        location += "  ·  " + " ".join(f"#{tag}" for tag in server.tags)
    text.append(_fit(location, 33), style=palette.muted)
    text.append("\n")
    text.append("─" * 33 + "\n", style=palette.border)

    if metrics is None:
        if snapshot.status is ServerStatus.CHECKING:
            text.append("Waiting for the first sample…\n", style=palette.muted)
        else:
            text.append("CONNECTION LOST\n", style=f"bold {palette.offline}")
            if snapshot.error:
                for line in textwrap.wrap(snapshot.error, width=31)[:4]:
                    text.append(line + "\n", style=palette.offline)
            text.append("\n")
            _kv(text, "LAST ONLINE", relative_time(snapshot.last_online), palette)
            _kv(
                text,
                "CHECKED",
                snapshot.checked_at.astimezone().strftime("%H:%M:%S"),
                palette,
            )
            if snapshot.server.transport == "ssh":
                _kv(text, "HOST", snapshot.server.endpoint, palette)
        return text

    _section(text, "system", palette)
    _kv(text, "OS", _fit(metrics.os_name, 25), palette)
    _kv(text, "KERNEL", _fit(metrics.kernel, 25), palette)
    uptime = human_uptime(metrics.uptime_seconds)
    poll = f"{snapshot.poll_ms:.0f}ms" if snapshot.poll_ms is not None else "—"
    text.append(f"{'UPTIME':<8}", style=palette.muted)
    text.append(f"{uptime:<12}", style=palette.text)
    text.append("POLL ", style=palette.muted)
    text.append(poll + "\n", style=palette.soft)
    _kv(text, "ARCH", f"{metrics.arch} · {metrics.cpu_count} cores", palette)
    if availability_24h is not None:
        _kv(text, "AVAIL", f"{availability_24h:.1f}% · 24h", palette)

    text.append("\n")
    _section(text, "resources", palette)
    _gauge_line(
        text,
        "CPU",
        metrics.cpu_percent,
        thresholds.cpu,
        f"{metrics.cpu_count} cores",
        palette,
    )
    _gauge_line(
        text,
        "MEM",
        metrics.memory_percent,
        thresholds.memory,
        f"{compact_bytes(metrics.memory_used)} / {compact_bytes(metrics.memory_total)}",
        palette,
    )
    _gauge_line(
        text,
        "DISK",
        metrics.disk_percent,
        thresholds.disk,
        f"{compact_bytes(metrics.disk_used)} / {compact_bytes(metrics.disk_total)}",
        palette,
    )
    load_ratio = metrics.load_per_core
    if load_ratio >= thresholds.load_per_core:
        load_color = palette.red
    elif load_ratio >= thresholds.load_per_core * 0.85:
        load_color = palette.amber
    else:
        load_color = palette.cyan
    text.append(f"{'LOAD':<5}", style=palette.muted)
    text.append(
        f"{metrics.load1:.2f} {metrics.load5:.2f} {metrics.load15:.2f}",
        style=load_color,
    )
    text.append(f"  {metrics.process_count} proc\n", style=palette.soft)
    if metrics.swap_total:
        _gauge_line(
            text,
            "SWAP",
            metrics.swap_percent,
            80,
            f"{compact_bytes(metrics.swap_used)} / {compact_bytes(metrics.swap_total)}",
            palette,
        )

    text.append("\n")
    _section(text, "cpu trend", palette)
    text.append(
        _sparkline(snapshot.cpu_history, palette, width=27, threshold=thresholds.cpu)
    )
    text.append(f"  {len(snapshot.cpu_history)}p\n", style=palette.muted)

    text.append("\n")
    _section(text, "network", palette)
    text.append("RX  ", style=palette.muted)
    text.append(f"{compact_rate(snapshot.rx_rate):<9}", style=palette.cyan)
    text.append(f" total {compact_bytes(metrics.net_rx_total)}\n", style=palette.soft)
    text.append("TX  ", style=palette.muted)
    text.append(f"{compact_rate(snapshot.tx_rate):<9}", style=palette.green)
    text.append(f" total {compact_bytes(metrics.net_tx_total)}\n", style=palette.soft)

    if snapshot.issues:
        text.append("\n")
        _section(text, "attention", palette)
        for issue in snapshot.issues:
            text.append("▲ ", style=palette.amber)
            text.append(issue + "\n", style=palette.amber)

    if metrics.services:
        text.append("\n")
        _section(text, "services", palette)
        for service in metrics.services:
            text.append_text(_service_line(service.name, service.state, palette))
            text.append("\n")

    text.append("\n")
    text.append("LAST SAMPLE ", style=palette.muted)
    text.append(relative_time(snapshot.checked_at), style=palette.soft)
    return text


def footer_text(
    interval: float,
    palette: Palette,
    *,
    compact: bool = False,
    auto_page_enabled: bool = True,
    auto_page_interval: float = 6.0,
) -> Text:
    text = Text()
    auto_label = "auto on" if auto_page_enabled else "auto off"
    for key, label in (
        ("↑↓", "select"),
        ("r", "refresh"),
        ("p", "pause"),
        ("a", auto_label),
        ("g", "group"),
        ("q", "quit"),
    ):
        text.append(f" {key} ", style=f"bold {palette.text} on {palette.chip_bg}")
        text.append(f" {label}   ", style=palette.soft)
    if not compact:
        text.append("·   agentless SSH · ", style=palette.muted)
        text.append(f"{interval:g}s poll · ", style=palette.muted)
        text.append("auto-page ", style=palette.muted)
        text.append(
            f"{auto_page_interval:g}s" if auto_page_enabled else "off",
            style=palette.soft if auto_page_enabled else palette.muted,
        )
    return text


def brand_text(palette: Palette) -> Text:
    text = Text()
    text.append("◆ ", style=f"bold {palette.accent}")
    text.append("SERVER", style=f"bold {palette.text}")
    text.append("DECK", style=f"bold {palette.accent}")
    text.append("   FLEET OPERATIONS", style=palette.muted)
    return text


def clock_text(palette: Palette, now: datetime | None = None) -> Text:
    now = now or datetime.now()
    text = Text()
    text.append(now.strftime("%a %d %b"), style=palette.muted)
    text.append("  ")
    text.append(now.strftime("%H:%M:%S"), style=f"bold {palette.text}")
    return text


def refresh_text(
    *,
    paused: bool,
    refreshing: bool,
    starting: bool,
    next_in: float | None,
    interval: float,
    palette: Palette,
    frame: int = 0,
) -> Text:
    """Draw a stable refresh indicator instead of a jittery relative clock."""

    text = Text()
    bar_width = 10
    if paused:
        label = "⏸ PAUSED"
    elif refreshing:
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        label = f"{spinner} SYNC"
    elif starting:
        label = "○ START"
    else:
        label = "● LIVE"

    text.append(f"{label:<8}", style=palette.text if not starting else palette.muted)
    text.append(" ")
    if paused or starting or refreshing:
        text.append("░" * bar_width, style=palette.border)
        return text

    progress = 0.0
    if interval > 0 and next_in is not None:
        progress = max(0.0, min(1.0, 1.0 - next_in / interval))
    filled = int(round(progress * bar_width))
    text.append("█" * filled, style=palette.soft)
    text.append("░" * (bar_width - filled), style=palette.border)
    return text
