"""Textual terminal user interface for ServerDeck."""

from __future__ import annotations

import contextlib
import time
from dataclasses import replace
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import DataTable, Static

from .alerts import detect_alerts
from .config import Config, Thresholds
from .history import HistoryStore
from .models import ServerSnapshot
from .monitor import Monitor, MonitorBase, initial_snapshot
from .render import (
    brand_text,
    clock_text,
    detail_text,
    footer_text,
    refresh_text,
    summary_line,
    table_cells,
)
from .themes import Palette, palette_for

WIDE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("host", "HOST", 17),
    ("uptime", "UPTIME", 8),
    ("cpu", "CPU", 11),
    ("mem", "MEM", 11),
    ("disk", "DISK", 11),
    ("load", "LOAD", 6),
    ("net", "NET RX / TX", 17),
    ("status", "STATUS", 10),
)
SPLIT_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("host", "HOST", 16),
    ("cpu", "CPU", 11),
    ("mem", "MEM", 11),
    ("disk", "DISK", 11),
    ("net", "NET RX / TX", 17),
    ("status", "STATUS", 10),
)
COMPACT_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("host", "HOST", 14),
    ("uptime", "UPTIME", 7),
    ("cpu", "CPU", 10),
    ("mem", "MEM", 10),
    ("disk", "DISK", 10),
    ("status", "STATUS", 10),
)


class ServerDeckApp(App[None]):
    """A compact, colorful fleet monitor that works over plain SSH."""

    CSS_PATH = "serverdeck.tcss"
    TITLE = "ServerDeck"
    SUB_TITLE = "fleet operations"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit", show=False, priority=True),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("p", "toggle_pause", "Pause", show=False),
        Binding("a", "toggle_auto_page", "Auto-page", show=False),
        Binding("g", "cycle_group", "Group filter", show=False),
    ]

    def __init__(
        self,
        config: Config,
        monitor: MonitorBase | None = None,
        *,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self.thresholds: Thresholds = config.settings.thresholds
        self.palette: Palette = palette_for(config.settings.theme)
        self._monitor: MonitorBase = monitor or Monitor(config)
        self._demo = demo
        self._snapshots: dict[str, ServerSnapshot] = {
            server.id: initial_snapshot(server) for server in config.servers
        }
        self._selected_id: str | None = config.servers[0].id if config.servers else None
        self._history: HistoryStore | None = None
        self._history_error: str | None = None
        if config.settings.history:
            try:
                self._history = HistoryStore(
                    config.settings.history_db, config.settings.history_days
                )
                for server in config.servers:
                    previous = self._history.recent_cpu(
                        server.id, config.settings.history_points
                    )
                    if previous:
                        self._snapshots[server.id] = replace(
                            self._snapshots[server.id], cpu_history=previous
                        )
            except Exception as exc:
                self._history_error = f"{type(exc).__name__}: {exc}"
        self._paused = False
        self._refreshing = False
        self._auto_page_enabled = config.settings.auto_page
        self._auto_page_timer: Timer | None = None
        self._row_reveal_timer: Timer | None = None
        self._initial_rows_loading = False
        self._initial_row_index = 0
        self._detail_switch_serial = 0
        self._last_finished: float | None = None
        self._refresh_frame = 0
        self._last_clock: str | None = None
        self._layout_key: tuple[tuple[str, int], ...] | None = None
        self._detail_visible = True
        self._group_filter: str | None = None
        self._groups: tuple[str, ...] = tuple(
            dict.fromkeys(server.group for server in config.servers)
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="topbar"):
            with Horizontal(id="masthead"):
                yield Static(brand_text(self.palette), id="brand")
                yield Static(clock_text(self.palette), id="clock")
            with Horizontal(id="summary-row"):
                yield Static(
                    summary_line(self._snapshots.values(), self.palette),
                    id="summary",
                )
                yield Static("", id="refresh-state")
        with Horizontal(id="body"):
            with Vertical(id="table-panel"):
                yield DataTable(
                    id="server-table",
                    cursor_type="row",
                    cursor_foreground_priority="renderable",
                    zebra_stripes=False,
                )
            with Vertical(id="detail-panel"), VerticalScroll(id="detail-scroll"):
                yield Static("", id="detail-content")
        yield Static(
            footer_text(
                self.config.settings.refresh_interval,
                self.palette,
                auto_page_enabled=self._auto_page_enabled,
                auto_page_interval=self.config.settings.auto_page_interval,
            ),
            id="footer",
        )

    def on_mount(self) -> None:
        table = self.query_one("#server-table", DataTable)
        self._table = table
        self.screen.add_class(f"theme-{self.config.settings.theme}")
        self._update_fleet_title()
        self.query_one("#detail-panel").border_title = " INSPECT "
        self._apply_visibility()
        self._initial_rows_loading = True
        self._configure_columns(force=True, include_rows=False)
        table.focus()
        self._update_header()
        self.set_interval(0.25, self._tick)
        if self._history_error:
            self.notify(
                f"history disabled: {self._history_error}",
                title="history unavailable",
                severity="warning",
                timeout=8,
            )
        self._start_refresh()
        self._start_initial_row_reveal()

    def _table_widget(self) -> DataTable:
        return self.query_one("#server-table", DataTable)

    def _visible_servers(self) -> tuple:
        if self._group_filter is None:
            return self.config.servers
        return tuple(
            server
            for server in self.config.servers
            if server.group == self._group_filter
        )

    def _visible_snapshots(self) -> list[ServerSnapshot]:
        return [self._snapshots[server.id] for server in self._visible_servers()]

    def _update_fleet_title(self) -> None:
        if self._group_filter is None:
            title = " FLEET "
        else:
            title = f" FLEET · {self._group_filter} "
        self.query_one("#table-panel").border_title = title

    def _columns(self) -> tuple[tuple[str, str, int], ...]:
        width = self.size.width
        if self._detail_visible and width < 152:
            return SPLIT_COLUMNS
        if width >= 112:
            return WIDE_COLUMNS
        return COMPACT_COLUMNS

    def _configure_columns(
        self, *, force: bool = False, include_rows: bool = True
    ) -> None:
        columns = self._columns()
        signature = tuple((key, column_width) for key, _, column_width in columns)
        if not force and signature == self._layout_key:
            return
        was_revealing = self._initial_rows_loading
        if was_revealing and include_rows:
            self._initial_rows_loading = False
            self._stop_row_reveal_timer()
        self._layout_key = signature
        table = self._table_widget()
        table.clear(columns=True)
        for key, label, column_width in columns:
            table.add_column(
                Text(label, style=f"bold {self.palette.accent}"),
                width=column_width,
                key=key,
            )
        if not include_rows:
            return
        visible = self._visible_servers()
        for server in visible:
            snapshot = self._snapshots[server.id]
            cells = table_cells(
                snapshot,
                self.thresholds,
                self.palette,
                compact=columns is COMPACT_COLUMNS,
            )
            table.add_row(
                *(cells[key] for key in self._visible_keys(columns)),
                key=server.id,
            )
        if self._selected_id not in {server.id for server in visible}:
            self._selected_id = visible[0].id if visible else None
        self._select_row(self._selected_id)
        if was_revealing:
            self._configure_auto_page_timer()

    def _apply_visibility(self) -> None:
        width = self.size.width
        visible = width >= 136 and self.size.height >= 24
        self._detail_visible = visible
        self.query_one("#detail-panel").display = visible
        self.query_one("#refresh-state").display = width >= 110
        self.query_one("#footer", Static).update(
            footer_text(
                self.config.settings.refresh_interval,
                self.palette,
                compact=width < 130,
                auto_page_enabled=self._auto_page_enabled,
                auto_page_interval=self.config.settings.auto_page_interval,
            )
        )
        self._update_summary()
        self._update_header()

    def _visible_keys(
        self, columns: tuple[tuple[str, str, int], ...]
    ) -> tuple[str, ...]:
        return tuple(key for key, _, _ in columns)

    def _select_row(self, server_id: str | None) -> None:
        table = self._table_widget()
        if not server_id:
            return
        for index, server in enumerate(self._visible_servers()):
            if server.id == server_id:
                with contextlib.suppress(Exception):
                    table.move_cursor(row=index, animate=False)
                return

    def on_resize(self) -> None:
        self._apply_visibility()
        if self.is_mounted:
            self._configure_columns()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        previous = self._selected_id
        self._selected_id = str(event.row_key.value)
        self._update_detail(
            animate=previous != self._selected_id and not self._initial_rows_loading
        )
        if self._auto_page_timer is not None and not self._paused:
            self._auto_page_timer.reset()

    def _tick(self) -> None:
        self._refresh_frame += 1
        clock = clock_text(self.palette)
        if clock.plain != self._last_clock:
            self._last_clock = clock.plain
            self.query_one("#clock", Static).update(clock)
        self._update_header()
        if self._paused or self._refreshing:
            return
        if self._last_finished is None:
            self._start_refresh()
            return
        if (
            time.monotonic() - self._last_finished
            >= self.config.settings.refresh_interval
        ):
            self._start_refresh()

    def _start_initial_row_reveal(self) -> None:
        servers = self._visible_servers()
        if not servers:
            self._initial_rows_loading = False
            self._configure_auto_page_timer()
            return
        self._initial_row_index = 0
        self._row_reveal_timer = self.set_interval(0.05, self._reveal_next_server_row)

    def _stop_row_reveal_timer(self) -> None:
        if self._row_reveal_timer is not None:
            self._row_reveal_timer.stop()
            self._row_reveal_timer = None

    def _reveal_next_server_row(self) -> None:
        if not self._initial_rows_loading:
            self._stop_row_reveal_timer()
            return
        servers = self._visible_servers()
        if self._initial_row_index >= len(servers):
            self._finish_initial_row_reveal()
            return

        server = servers[self._initial_row_index]
        snapshot = self._snapshots[server.id]
        table = self._table_widget()
        columns = self._columns()
        cells = table_cells(
            snapshot,
            self.thresholds,
            self.palette,
            compact=columns is COMPACT_COLUMNS,
        )
        table.add_row(
            *(cells[key] for key in self._visible_keys(columns)),
            key=server.id,
        )
        if self._initial_row_index == 0:
            self._selected_id = server.id
            with contextlib.suppress(Exception):
                table.move_cursor(row=0, animate=False, scroll=True)
            self._update_detail()
        self._initial_row_index += 1
        if self._initial_row_index >= len(servers):
            self._finish_initial_row_reveal()

    def _finish_initial_row_reveal(self) -> None:
        self._stop_row_reveal_timer()
        if not self._initial_rows_loading:
            return
        self._initial_rows_loading = False
        self._configure_auto_page_timer()

    def _configure_auto_page_timer(self) -> None:
        if self._initial_rows_loading:
            return
        if self._auto_page_timer is not None:
            self._auto_page_timer.stop()
            self._auto_page_timer = None
        if self._auto_page_enabled and len(self._visible_servers()) > 1:
            self._auto_page_timer = self.set_interval(
                self.config.settings.auto_page_interval, self._auto_page_tick
            )

    def _auto_page_tick(self) -> None:
        if not self._auto_page_enabled or self._paused:
            return
        self._advance_auto_page()

    def _advance_auto_page(self) -> None:
        servers = self._visible_servers()
        if not self._auto_page_enabled or len(servers) < 2:
            return
        current = self._selected_id or servers[0].id
        indexes = {server.id: index for index, server in enumerate(servers)}
        next_index = (indexes.get(current, 0) + 1) % len(servers)
        next_server = servers[next_index]
        self._selected_id = next_server.id
        with contextlib.suppress(Exception):
            self._table_widget().move_cursor(row=next_index, animate=False, scroll=True)

    def _start_refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._update_header()
        self._collect_worker()

    @work(thread=True, group="collect", exclusive=True, exit_on_error=False)
    def _collect_worker(self) -> None:
        previous = dict(self._snapshots)
        try:
            self._monitor.collect_all(
                self.config.servers,
                previous,
                self._snapshot_from_worker,
            )
        except Exception as exc:
            # A callback failure during shutdown must not leave the UI spinning.
            with contextlib.suppress(Exception):
                self.call_from_thread(
                    self.notify,
                    f"collection worker error: {type(exc).__name__}: {exc}",
                    severity="error",
                )
        finally:
            with contextlib.suppress(Exception):
                self.call_from_thread(self._finish_refresh)

    def _snapshot_from_worker(self, snapshot: ServerSnapshot) -> None:
        # During shutdown the message loop may already be gone.
        with contextlib.suppress(Exception):
            self.call_from_thread(self._apply_snapshot, snapshot)

    def _row_exists(self, server_id: str) -> bool:
        try:
            self._table_widget().get_row_index(server_id)
            return True
        except Exception:
            return False

    def _apply_snapshot(self, snapshot: ServerSnapshot) -> None:
        previous = self._snapshots.get(snapshot.server.id)
        self._snapshots[snapshot.server.id] = snapshot
        if self.config.settings.alerts:
            for alert in detect_alerts(previous, snapshot):
                self.notify(
                    alert.message,
                    title=alert.title,
                    severity=alert.severity,
                    timeout=6,
                )
        if self._history is not None:
            try:
                self._history.record(snapshot)
            except Exception as exc:
                self._history_error = f"{type(exc).__name__}: {exc}"
                self._history.close()
                self._history = None
                self.notify(
                    f"history disabled: {self._history_error}",
                    title="history unavailable",
                    severity="warning",
                    timeout=8,
                )
        if not self._row_exists(snapshot.server.id):
            # The initial reveal animation hasn't added this row yet. Its
            # current snapshot will be rendered when the row appears.
            self._update_summary()
            if self._selected_id == snapshot.server.id:
                self._update_detail()
            return
        table = self._table_widget()
        columns = self._columns()
        cells = table_cells(
            snapshot,
            self.thresholds,
            self.palette,
            compact=columns is COMPACT_COLUMNS,
        )
        try:
            for key in self._visible_keys(columns):
                table.update_cell(snapshot.server.id, key, cells[key])
        except Exception:
            # Row was rebuilt between scheduling and delivery; rebuild safely.
            if not self._initial_rows_loading:
                self._configure_columns(force=True)
                self._apply_snapshot(snapshot)
            return
        self._update_summary()
        if self._selected_id == snapshot.server.id:
            self._update_detail()

    def _finish_refresh(self) -> None:
        self._refreshing = False
        self._last_finished = time.monotonic()
        self._update_header()

    def _update_summary(self) -> None:
        summary = summary_line(self._visible_snapshots(), self.palette)
        if self.size.width < 110:
            if self._paused:
                summary.append("   ⏸ paused", style="bold #fbbf24")
            elif self._refreshing:
                summary.append("   ↻ collecting", style="#38bdf8")
        self.query_one("#summary", Static).update(summary)

    def _update_header(self) -> None:
        interval = self.config.settings.refresh_interval
        next_in = None
        if (
            self._last_finished is not None
            and not self._paused
            and not self._refreshing
        ):
            next_in = max(0.0, interval - (time.monotonic() - self._last_finished))
        self.query_one("#refresh-state", Static).update(
            refresh_text(
                paused=self._paused,
                refreshing=self._refreshing,
                starting=self._last_finished is None,
                next_in=next_in,
                interval=interval,
                palette=self.palette,
                frame=self._refresh_frame,
            )
        )

    def _update_detail(self, *, animate: bool = False) -> None:
        if not self._selected_id:
            return
        snapshot = self._snapshots.get(self._selected_id)
        if snapshot is None:
            return
        content = self.query_one("#detail-content", Static)
        panel = self.query_one("#detail-panel")
        availability = None
        if self._history is not None:
            try:
                availability = self._history.availability(snapshot.server.id, 24)
            except Exception:
                availability = None
        content.update(
            detail_text(
                snapshot,
                self.thresholds,
                self.palette,
                availability_24h=availability,
            )
        )
        panel.border_subtitle = f" {snapshot.server.name} "
        if animate:
            self._animate_detail_switch(snapshot.server.name)

    def _animate_detail_switch(self, server_name: str) -> None:
        content = self.query_one("#detail-content", Static)
        panel = self.query_one("#detail-panel")
        content.styles.opacity = 0.15
        content.styles.animate("opacity", 1.0, duration=0.28, easing="out_cubic")
        with contextlib.suppress(Exception):
            self.query_one("#detail-scroll", VerticalScroll).scroll_to(
                y=0, animate=False
            )
        self._detail_switch_serial += 1
        token = self._detail_switch_serial
        panel.border_title = f" INSPECT → {server_name} "

        def restore_title() -> None:
            if self._detail_switch_serial == token:
                panel.border_title = " INSPECT "

        self.set_timer(0.55, restore_title)

    def action_refresh(self) -> None:
        self._start_refresh()

    def action_cycle_group(self) -> None:
        choices: tuple[str | None, ...] = (None, *self._groups)
        try:
            index = choices.index(self._group_filter)
        except ValueError:
            index = 0
        self._group_filter = choices[(index + 1) % len(choices)]
        visible = self._visible_servers()
        self._selected_id = visible[0].id if visible else None
        self._update_fleet_title()
        self._configure_columns(force=True)
        self._update_summary()
        self._update_detail()
        self._configure_auto_page_timer()

    def action_toggle_auto_page(self) -> None:
        self._auto_page_enabled = not self._auto_page_enabled
        self._configure_auto_page_timer()
        self._apply_visibility()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._auto_page_timer is not None:
            if self._paused:
                self._auto_page_timer.pause()
            else:
                self._auto_page_timer.resume()
                self._auto_page_timer.reset()
        self._update_header()
        if (
            not self._paused
            and not self._refreshing
            and (
                self._last_finished is not None
                and time.monotonic() - self._last_finished
                >= self.config.settings.refresh_interval
            )
        ):
            self._start_refresh()

    def on_unmount(self) -> None:
        with contextlib.suppress(Exception):
            self._monitor.close()
        if self._history is not None:
            self._history.close()
