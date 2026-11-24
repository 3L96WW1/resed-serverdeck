from __future__ import annotations

from dataclasses import replace

from serverdeck.demo import DEMO_CONFIG
from serverdeck.models import ServerStatus
from serverdeck.monitor import initial_snapshot
from serverdeck.render import refresh_text, status_badge, summary_line
from serverdeck.themes import PALETTES, palette_for


def test_named_themes_exist():
    assert set(PALETTES) == {"graphite", "mono", "black", "midnight", "console"}


def test_mono_palette_is_grayscale():
    palette = palette_for("mono")
    for color in (
        palette.green,
        palette.red,
        palette.online,
        palette.offline,
        palette.amber,
        palette.cyan,
        palette.muted,
        palette.text,
        palette.soft,
        palette.border,
        palette.accent,
        palette.chip_bg,
    ):
        channels = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
        assert channels[0] == channels[1] == channels[2], color


def test_unknown_theme_falls_back_to_mono():
    assert palette_for("does-not-exist") is PALETTES["mono"]


def test_console_theme_is_high_contrast_and_plain():
    palette = PALETTES["console"]
    assert palette.plain is True
    assert palette.text == "bright_white"
    assert palette.muted == "white"
    assert palette.online == "bright_green"
    assert palette.offline == "bright_red"


def test_console_theme_uses_ascii_progress_bars():
    snapshot = replace(
        initial_snapshot(DEMO_CONFIG.servers[0]),
        status=ServerStatus.ONLINE,
    )
    summary = summary_line([snapshot], PALETTES["console"])
    assert summary.plain.startswith("* ")
    output = refresh_text(
        paused=False,
        refreshing=False,
        starting=False,
        next_in=3,
        interval=6,
        palette=PALETTES["console"],
    )
    assert len(output.plain) == 19
    assert "█" not in output.plain
    assert "░" not in output.plain
    assert "#" in output.plain


def test_colored_themes_use_bright_semantic_status_colors():
    for name in ("graphite", "black", "midnight"):
        palette = PALETTES[name]
        assert palette.online == "#39ff14"
        assert palette.offline == "#ff3b30"


def test_status_badge_uses_bright_semantic_colors():
    online = status_badge(ServerStatus.ONLINE, PALETTES["graphite"])
    offline = status_badge(ServerStatus.OFFLINE, PALETTES["graphite"])
    assert PALETTES["graphite"].online in str(online.style)
    assert PALETTES["graphite"].offline in str(offline.style)


def test_summary_uses_neutral_shades_instead_of_status_colors():
    snapshots = [
        replace(initial_snapshot(DEMO_CONFIG.servers[0]), status=ServerStatus.ONLINE),
        replace(initial_snapshot(DEMO_CONFIG.servers[1]), status=ServerStatus.DEGRADED),
        replace(initial_snapshot(DEMO_CONFIG.servers[2]), status=ServerStatus.OFFLINE),
    ]
    palette = PALETTES["graphite"]
    summary = summary_line(snapshots, palette)
    styles = " ".join(str(span.style) for span in summary.spans)
    assert palette.online not in styles
    assert palette.offline not in styles
    assert palette.text in styles
    assert palette.soft in styles


def test_refresh_indicator_is_fixed_width_and_has_no_relative_text():
    states = [
        dict(paused=False, refreshing=False, starting=False, next_in=4.5),
        dict(paused=True, refreshing=False, starting=False, next_in=None),
        dict(paused=False, refreshing=True, starting=False, next_in=None),
        dict(paused=False, refreshing=False, starting=True, next_in=None),
    ]
    outputs = [
        refresh_text(
            **state,
            interval=6,
            palette=PALETTES["black"],
            frame=3,
        )
        for state in states
    ]
    assert {len(output.plain) for output in outputs} == {19}
    assert all("updated" not in output.plain for output in outputs)
