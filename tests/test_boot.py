from __future__ import annotations

from dataclasses import replace
from io import StringIO

from rich.console import Console

from serverdeck.boot import build_boot_lines, show_boot_animation
from serverdeck.demo import DEMO_CONFIG
from serverdeck.themes import PALETTES


def test_boot_lines_describe_configuration():
    lines = build_boot_lines(DEMO_CONFIG)
    values = {line.label: line.value for line in lines}
    assert values["servers"] == "16 total · 1 local · 15 SSH"
    assert values["theme"].startswith("mono")
    assert values["auto-page"] == "on · 6s per server"
    assert values["refresh"] == "every 2s"


def test_boot_lines_show_disabled_auto_page():
    config = replace(
        DEMO_CONFIG,
        settings=replace(DEMO_CONFIG.settings, auto_page=False),
    )
    values = {line.label: line.value for line in build_boot_lines(config)}
    assert values["auto-page"] == "off"


def test_boot_animation_prints_log_lines_without_errors():
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=100)
    show_boot_animation(DEMO_CONFIG, PALETTES["graphite"], console=console, delay=0)
    text = output.getvalue()
    assert "SERVERDECK" in text
    assert "BOOT LOG" in text
    assert "initializing terminal dashboard" in text
    assert "entering dashboard" in text
    assert "16 total · 1 local · 15 SSH" in text
