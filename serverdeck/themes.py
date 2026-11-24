"""Color presets for the ServerDeck terminal UI.

The TUI uses these palettes for Rich text, while the matching CSS class in
``serverdeck.tcss`` controls the terminal-cell backgrounds.  Keeping both
declarations in one place makes each theme reproducible across terminals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ThemeName = Literal["graphite", "mono", "black", "midnight", "console"]
THEME_NAMES: tuple[ThemeName, ...] = (
    "graphite",
    "mono",
    "black",
    "midnight",
    "console",
)
DEFAULT_THEME: ThemeName = "mono"


@dataclass(frozen=True, slots=True)
class Palette:
    green: str
    red: str
    online: str
    offline: str
    amber: str
    cyan: str
    muted: str
    text: str
    soft: str
    border: str
    accent: str
    chip_bg: str
    plain: bool = False


# The classic deep-navy interface: colored accents on a blue-black background.
MIDNIGHT = Palette(
    green="#34d399",
    red="#fb7185",
    online="#39ff14",
    offline="#ff3b30",
    amber="#fbbf24",
    cyan="#38bdf8",
    muted="#64748b",
    text="#dbe7f3",
    soft="#94a3b8",
    border="#1e3a4a",
    accent="#22d3ee",
    chip_bg="#173242",
)

# Pure black with the same saturated accent colors.
BLACK = Palette(
    green="#34d399",
    red="#fb7185",
    online="#39ff14",
    offline="#ff3b30",
    amber="#fbbf24",
    cyan="#38bdf8",
    muted="#737373",
    text="#e5e5e5",
    soft="#a3a3a3",
    border="#1f1f1f",
    accent="#22d3ee",
    chip_bg="#1a1a1a",
)

# The original terminal no-color look: a soft #121212 charcoal background and
# muted grayscale text.  This is a deliberate match for Textual's NO_COLOR
# rendering of the first version, not just a desaturated colored theme.
GRAPHITE = Palette(
    green="#c2c2c2",
    red="#d8d8d8",
    online="#39ff14",
    offline="#ff3b30",
    amber="#a8a8a8",
    cyan="#b3b3b3",
    muted="#6e6e6e",
    text="#d2d2d2",
    soft="#9a9a9a",
    border="#2a2a2a",
    accent="#a8a8a8",
    chip_bg="#1d1d1d",
)

# Stark monochrome theme on true-black surfaces.
MONO = Palette(
    green="#dedede",
    red="#ffffff",
    online="#e8e8e8",
    offline="#ffffff",
    amber="#b9b9b9",
    cyan="#cccccc",
    muted="#666666",
    text="#e4e4e4",
    soft="#9e9e9e",
    border="#2a2a2a",
    accent="#b8b8b8",
    chip_bg="#1e1e1e",
)

# High-contrast ANSI palette for the Linux text console and other 8-color
# terminals.  It intentionally avoids low-contrast grays and uses ASCII
# gauges so older console fonts can still render every status.
CONSOLE = Palette(
    green="bright_green",
    red="bright_red",
    online="bright_green",
    offline="bright_red",
    amber="bright_yellow",
    cyan="bright_cyan",
    muted="white",
    text="bright_white",
    soft="white",
    border="blue",
    accent="bright_cyan",
    chip_bg="blue",
    plain=True,
)

PALETTES: dict[ThemeName, Palette] = {
    "graphite": GRAPHITE,
    "mono": MONO,
    "black": BLACK,
    "midnight": MIDNIGHT,
    "console": CONSOLE,
}


def palette_for(theme: str) -> Palette:
    try:
        return PALETTES[theme]  # type: ignore[index]
    except KeyError:
        # Configuration validation should make this unreachable, but keep the
        # renderer safe for programmatic callers.
        return MONO


def theme_description(theme: str) -> str:
    return {
        "graphite": "charcoal / restored first black version",
        "mono": "pure black / monochrome",
        "black": "pure black / color accents",
        "midnight": "deep navy / color accents",
        "console": "high contrast / 8-color console",
    }.get(theme, "unknown")
