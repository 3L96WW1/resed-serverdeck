from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from serverdeck.app import COMPACT_COLUMNS, WIDE_COLUMNS, ServerDeckApp
from serverdeck.cli import main
from serverdeck.demo import DEMO_CONFIG, DemoMonitor
from serverdeck.models import ServerStatus


@pytest.mark.asyncio
async def test_dashboard_starts_with_demo_data():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(2.5)
        assert len(app._snapshots) == len(DEMO_CONFIG.servers)
        assert app._snapshots["cache-01"].status is ServerStatus.OFFLINE
        table = app.query_one("#server-table")
        assert len(table.columns) == len(WIDE_COLUMNS)
        assert app._detail_visible is True
        assert app.screen.has_class("theme-mono")
        assert app.screen.styles.background.hex == "#000000"


@pytest.mark.asyncio
async def test_dashboard_responds_to_resize():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(1.2)
        table = app.query_one("#server-table")
        assert len(table.columns) == len(WIDE_COLUMNS)
        await pilot.resize_terminal(140, 40)
        await pilot.pause(0.4)
        assert app._detail_visible is False
        assert len(table.columns) == len(WIDE_COLUMNS)
        await pilot.resize_terminal(128, 48)
        await pilot.pause(0.4)
        assert app._detail_visible is False
        assert len(table.columns) == len(WIDE_COLUMNS)
        await pilot.resize_terminal(146, 48)
        await pilot.pause(0.4)
        assert app._detail_visible is False
        assert len(table.columns) == len(WIDE_COLUMNS)
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.4)
        assert app._detail_visible is False
        assert len(table.columns) == len(COMPACT_COLUMNS)
        assert app.query_one("#refresh-state").display is False


@pytest.mark.asyncio
async def test_inspect_panel_can_be_toggled_on_narrow_screen():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(128, 48)) as pilot:
        await pilot.pause(1.0)
        table = app.query_one("#server-table")
        assert app._detail_visible is False
        assert len(table.columns) == len(WIDE_COLUMNS)
        await pilot.press("i")
        await pilot.pause(0.2)
        assert app._detail_visible is True
        assert len(table.columns) == len(COMPACT_COLUMNS)
        await pilot.press("i")
        await pilot.pause(0.2)
        assert app._detail_visible is False
        assert len(table.columns) == len(WIDE_COLUMNS)


class SlowDemoMonitor(DemoMonitor):
    def collect(self, server, previous):
        time.sleep(0.35)
        return super().collect(server, previous)


@pytest.mark.asyncio
async def test_server_list_reveals_rows_one_by_one():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        table = app._table_widget()
        assert app._initial_rows_loading is True
        assert table.row_count < len(DEMO_CONFIG.servers)
        await pilot.pause(0.18)
        partial = table.row_count
        assert 0 < partial < len(DEMO_CONFIG.servers)
        await pilot.pause(1.0)
        assert table.row_count == len(DEMO_CONFIG.servers)
        assert app._initial_rows_loading is False


@pytest.mark.asyncio
async def test_inspect_switch_animation():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(1.1)
        app._table_widget().move_cursor(row=5, animate=False)
        await pilot.pause(0.08)
        panel = app.query_one("#detail-panel")
        content = app.query_one("#detail-content")
        assert "INSPECT →" in panel.border_title
        assert content.styles.opacity < 1.0
        await pilot.pause(0.6)
        assert panel.border_title == " INSPECT "
        assert content.styles.opacity == 1.0


@pytest.mark.asyncio
async def test_table_columns_have_swapped_status_and_uptime():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(0.8)
        labels = [column.label.plain for column in app._table_widget().ordered_columns]
        assert labels[0] == "HOST"
        assert labels[1] == "UPTIME"
        assert labels[-1] == "STATUS"
        assert app._table_widget().cursor_foreground_priority == "renderable"


@pytest.mark.asyncio
async def test_auto_page_advances_and_wraps():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(0.8)
        assert app._selected_id == "atlas"
        app._advance_auto_page()
        assert app._selected_id == "web-01"
        for _ in range(len(DEMO_CONFIG.servers) - 1):
            app._advance_auto_page()
        assert app._selected_id == "atlas"


@pytest.mark.asyncio
async def test_auto_page_respects_config_and_toggle():
    config = replace(
        DEMO_CONFIG,
        settings=replace(DEMO_CONFIG.settings, auto_page=False),
    )
    app = ServerDeckApp(config, monitor=DemoMonitor())
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.8)
        assert app._auto_page_enabled is False
        app._advance_auto_page()
        assert app._selected_id == "atlas"
        await pilot.press("a")
        assert app._auto_page_enabled is True
        app._auto_page_tick()
        assert app._selected_id == "web-01"
        assert "auto on" in app.query_one("#footer").renderable.plain


@pytest.mark.asyncio
async def test_group_filter_cycles_visible_servers():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(1.2)
        await pilot.press("g")
        await pilot.pause(0.2)
        assert app._group_filter == "Default Server Group"
        assert app._table_widget().row_count == 1
        assert app._selected_id == "atlas"
        assert "Default Server Group" in app.query_one("#table-panel").border_title
        await pilot.press("g")
        await pilot.pause(0.2)
        assert app._group_filter == "Production Web"
        assert app._table_widget().row_count == 3


@pytest.mark.asyncio
async def test_pause_and_refresh_actions():
    app = ServerDeckApp(DEMO_CONFIG, monitor=SlowDemoMonitor(), demo=True)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(1.5)
        await pilot.press("p")
        assert app._paused is True
        await pilot.press("p")
        assert app._paused is False
        await pilot.press("r")
        assert app._refreshing is True
        await pilot.pause(0.8)
        assert app._refreshing is False


@pytest.mark.asyncio
async def test_row_selection_updates_detail():
    app = ServerDeckApp(DEMO_CONFIG, monitor=DemoMonitor(), demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(1.2)
        app._table_widget().move_cursor(row=2)
        await pilot.pause(0.2)
        assert app._selected_id == "db-01"
        detail = app.query_one("#detail-content")
        assert "db-01" in detail.renderable.plain
        assert "Data Services" in detail.renderable.plain


def test_cli_demo_once_no_color():
    project = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project)
    result = subprocess.run(
        [sys.executable, "-m", "serverdeck", "--demo", "--once", "--no-color"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "SERVERDECK" in output
    assert "10 online" in output
    assert "4 degraded" in output
    assert "2 offline" in output
    assert "16 hosts" in output
    assert "\x1b[" not in output


@pytest.mark.asyncio
async def test_history_feeds_availability_in_detail(tmp_path):
    config = replace(
        DEMO_CONFIG,
        settings=replace(
            DEMO_CONFIG.settings,
            history=True,
            history_db=tmp_path / "history.db",
        ),
    )
    app = ServerDeckApp(config, monitor=DemoMonitor())
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(1.3)
        detail = app.query_one("#detail-content").renderable.plain
        assert "AVAIL" in detail
        assert "100.0% · 24h" in detail


@pytest.mark.asyncio
async def test_midnight_theme_is_applied():
    config = replace(
        DEMO_CONFIG,
        settings=replace(DEMO_CONFIG.settings, theme="midnight"),
    )
    app = ServerDeckApp(config, monitor=DemoMonitor())
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause(0.8)
        assert app.screen.has_class("theme-midnight")
        assert app.screen.styles.background.hex == "#060D14"


def test_cli_theme_override(capsys):
    code = main(["--demo", "--check", "--theme", "black"])
    assert code == 0
    output = capsys.readouterr().out
    assert "theme:   black" in output


def test_cli_demo_json(capsys):
    code = main(["--demo", "--json"])
    assert code == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert len(payload["servers"]) == 16
    assert payload["servers"][0]["group"] == "Default Server Group"
    statuses = {server["id"]: server["status"] for server in payload["servers"]}
    assert statuses["cache-01"] == "offline"
    assert statuses["db-01"] == "degraded"
    assert payload["servers"][0]["metrics"]["cpu_percent"] >= 0


def test_check_config_demo(capsys):
    code = main(["--demo", "--check"])
    assert code == 0
    assert "configuration valid" in capsys.readouterr().out
