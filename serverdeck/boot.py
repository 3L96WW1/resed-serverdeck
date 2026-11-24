"""Startup boot-log animation shown in the terminal before the TUI starts."""

from __future__ import annotations

import time
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass

from rich.console import Console
from rich.text import Text

from . import __version__
from .config import Config
from .themes import Palette, theme_description


@dataclass(frozen=True, slots=True)
class BootLine:
    label: str
    value: str
    warning: bool = False


def _fit(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1].rstrip() + "…"


def build_boot_lines(config: Config) -> list[BootLine]:
    transports = Counter(server.transport for server in config.servers)
    paging = (
        f"on · {config.settings.auto_page_interval:g}s per server"
        if config.settings.auto_page
        else "off"
    )
    lines = [
        BootLine("version", f"ServerDeck {__version__}"),
        BootLine("config", _fit(str(config.path), 58)),
        BootLine(
            "servers",
            f"{len(config.servers)} total · "
            f"{transports['local']} local · {transports['ssh']} SSH",
        ),
        BootLine(
            "theme",
            f"{config.settings.theme} · {theme_description(config.settings.theme)}",
        ),
        BootLine("refresh", f"every {config.settings.refresh_interval:g}s"),
        BootLine("auto-page", paging),
        BootLine("ui", "initializing terminal dashboard"),
    ]
    for warning in config.warnings:
        lines.append(BootLine("warning", _fit(warning, 58), warning=True))
    return lines


def show_boot_animation(
    config: Config,
    palette: Palette,
    *,
    console: Console | None = None,
    delay: float = 0.16,
) -> None:
    """Print a short startup log with spinner frames, then let the TUI enter."""

    console = console or Console()
    console.print()
    header = Text()
    header.append("◆ ", style=f"bold {palette.accent}")
    header.append("SERVER", style=f"bold {palette.text}")
    header.append("DECK", style=f"bold {palette.accent}")
    header.append(f"  v{__version__}", style=palette.muted)
    console.print(header)
    console.print(Text("BOOT LOG", style=f"bold {palette.accent}"))
    console.print(Text("─" * 58, style=palette.border))

    for line in build_boot_lines(config):
        status = (
            console.status(
                f"[{palette.muted}]initializing {line.label}…[/]",
                spinner="dots",
            )
            if console.is_terminal
            else nullcontext()
        )
        with status:
            time.sleep(delay)
        marker = "!" if line.warning else "✓"
        marker_style = palette.amber if line.warning else palette.online
        style = palette.amber if line.warning else palette.text
        console.print(
            Text(f"  {marker} ", style=f"bold {marker_style}")
            + Text(f"{line.label:<10}", style=palette.muted)
            + Text(line.value, style=style)
        )

    console.print(Text("─" * 58, style=palette.border))
    console.print(Text("  entering dashboard…", style=f"italic {palette.muted}"))
    time.sleep(delay)
