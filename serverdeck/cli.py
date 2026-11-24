"""Command-line entry point for ServerDeck."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .app import ServerDeckApp
from .boot import show_boot_animation
from .config import Config, ConfigError, load_config
from .demo import DEMO_CONFIG, DemoMonitor
from .models import (
    ServerSnapshot,
    ServerStatus,
    snapshot_to_dict,
)
from .monitor import Monitor, MonitorBase, initial_snapshot
from .render import brand_text, load_cell, summary_line, table_cells
from .themes import THEME_NAMES, Palette, palette_for, theme_description


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serverdeck",
        description="A colorful terminal dashboard for local and remote Linux servers.",
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        help="YAML configuration file (default: ./serverdeck.yaml, then XDG config)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run with a built-in simulated fleet (no network access)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="print one snapshot and exit instead of starting the TUI",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print one JSON snapshot and exit (implies --once)",
    )
    parser.add_argument(
        "--theme",
        choices=THEME_NAMES,
        help="override the theme from the config: mono, black, or midnight",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colors in one-shot output",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the configuration and exit",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _resolve(args: argparse.Namespace) -> tuple[Config, MonitorBase]:
    if args.demo:
        return DEMO_CONFIG, DemoMonitor()
    config = load_config(args.config)
    return config, Monitor(config)


def _collect_once(config: Config, monitor: MonitorBase) -> list[ServerSnapshot]:
    snapshots = {server.id: initial_snapshot(server) for server in config.servers}
    console = Console(stderr=True)
    try:
        status_context = (
            console.status("[cyan]collecting fleet telemetry…[/]", spinner="dots")
            if console.is_terminal
            else nullcontext()
        )
        with status_context:
            first = monitor.collect_all(
                config.servers, snapshots, lambda snapshot: None
            )
            reachable = [
                server
                for server in config.servers
                if first[server.id].status
                in {ServerStatus.ONLINE, ServerStatus.DEGRADED}
            ]
            second: dict[str, ServerSnapshot] = {}
            if reachable:
                # A short gap gives network counters a meaningful sampling
                # window and avoids a zero-length first rate.
                time.sleep(0.35)
                second = monitor.collect_all(reachable, first, lambda snapshot: None)
                first.update(second)
    finally:
        monitor.close()
    return [first[server.id] for server in config.servers]


def _print_json(snapshots: list[ServerSnapshot]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "servers": [snapshot_to_dict(snapshot) for snapshot in snapshots],
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _once_table(
    snapshots: list[ServerSnapshot],
    config: Config,
    console_width: int,
    palette: Palette,
) -> Table:
    if console_width >= 110:
        layout = "full"
        keys = (
            "host",
            "uptime",
            "cpu",
            "mem",
            "disk",
            "load",
            "net",
            "status",
            "fetch",
        )
    elif console_width >= 95:
        layout = "medium"
        keys = ("host", "uptime", "cpu", "mem", "disk", "net", "status")
    else:
        layout = "compact"
        keys = ("host", "uptime", "cpu", "mem", "disk", "status")

    labels = {
        "host": ("HOST", 12),
        "status": ("STATUS", 10),
        "cpu": ("CPU", 11),
        "mem": ("MEM", 11),
        "disk": ("DISK", 11),
        "load": ("LOAD", 6),
        "net": ("NET RX / TX", 15),
        "uptime": ("UPTIME", 8),
        "fetch": ("POLL", 7),
    }
    table = Table(
        box=box.SIMPLE_HEAVY,
        border_style=palette.border,
        header_style=f"bold {palette.cyan}",
        expand=False,
        pad_edge=False,
        padding=(0, 1),
        show_edge=False,
    )
    for key in keys:
        label, width = labels[key]
        if key in {"load", "fetch"}:
            table.add_column(label, min_width=width, justify="right", no_wrap=True)
        else:
            table.add_column(label, min_width=width, no_wrap=True)

    for snapshot in snapshots:
        cells = table_cells(
            snapshot,
            config.settings.thresholds,
            palette,
            compact=layout == "compact",
        )
        if layout != "full":
            cells["host"] = Text(snapshot.server.name, style=f"bold {palette.text}")
        if snapshot.metrics is not None:
            cells["load"] = load_cell(
                snapshot.metrics, config.settings.thresholds, palette
            )
            fetch = (
                Text(f"{snapshot.poll_ms:.0f}ms", style=palette.muted)
                if snapshot.poll_ms is not None
                else Text("—", style=palette.muted)
            )
            cells["fetch"] = fetch
        table.add_row(*(cells.get(key, Text("—", style=palette.muted)) for key in keys))
    return table


def _print_once(
    snapshots: list[ServerSnapshot],
    config: Config,
    palette: Palette,
    *,
    color: bool,
) -> None:
    console = Console(no_color=not color, highlight=False)
    console.print()
    console.print(brand_text(palette))
    console.print(summary_line(snapshots, palette))
    console.print()
    console.print(_once_table(snapshots, config, console.width, palette))
    offline = [snap for snap in snapshots if snap.status is ServerStatus.OFFLINE]
    if offline:
        console.print()
        for snapshot in offline:
            console.print(
                Text("● ", style=palette.red)
                + Text(f"{snapshot.server.name}: ", style=f"bold {palette.text}")
                + Text(snapshot.error or "unreachable", style=palette.red)
            )
    healthy = sum(
        1
        for snapshot in snapshots
        if snapshot.status in {ServerStatus.ONLINE, ServerStatus.DEGRADED}
    )
    console.print(
        Text(
            f"\n{healthy}/{len(snapshots)} reachable · "
            f"refresh {config.settings.refresh_interval:g}s · "
            f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            style=palette.muted,
        )
    )
    console.print()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.demo and args.config:
        parser.error("--demo and --config cannot be used together")
    if args.json:
        args.once = True

    try:
        config, monitor = _resolve(args)
        if args.theme:
            config = replace(
                config, settings=replace(config.settings, theme=args.theme)
            )
    except ConfigError as exc:
        Console(stderr=True).print(f"[bold red]config error:[/] {exc}")
        return 2
    except Exception as exc:
        Console(stderr=True).print(
            f"[bold red]cannot start:[/] {type(exc).__name__}: {exc}"
        )
        return 2

    palette = palette_for(config.settings.theme)
    if args.check:
        console = Console()
        console.print(f"[bold {palette.green}]✓[/] configuration valid")
        console.print(f"  servers: [bold]{len(config.servers)}[/]")
        console.print(f"  config:  {config.path}", soft_wrap=True)
        console.print(
            f"  theme:   [bold]{config.settings.theme}[/]  "
            f"[dim]({theme_description(config.settings.theme)})[/]"
        )
        paging = (
            f"on · {config.settings.auto_page_interval:g}s/server"
            if config.settings.auto_page
            else "off"
        )
        console.print(f"  paging:  {paging}")
        console.print(f"  boot:    {'on' if config.settings.boot_animation else 'off'}")
        console.print(f"  alerts:  {'on' if config.settings.alerts else 'off'}")
        console.print(
            "  history: "
            + (
                f"on · {config.settings.history_days}d"
                if config.settings.history
                else "off"
            )
        )
        for warning in config.warnings:
            Console(stderr=True).print(f"[yellow]warning:[/] {warning}")
        monitor.close()
        return 0

    for warning in config.warnings:
        Console(stderr=True).print(f"[yellow]warning:[/] {warning}")

    console_mode = args.once or args.json or not sys.stdout.isatty()
    if console_mode:
        try:
            if args.json:
                snapshots = _collect_once(config, monitor)
                _print_json(snapshots)
            else:
                snapshots = _collect_once(config, monitor)
                _print_once(
                    snapshots,
                    config,
                    palette,
                    color=not args.no_color and sys.stdout.isatty(),
                )
            return 0
        except KeyboardInterrupt:
            Console(stderr=True).print("\ninterrupted", style="yellow")
            return 130
        except Exception as exc:
            Console(stderr=True).print(
                f"[bold red]collection failed:[/] {type(exc).__name__}: {exc}"
            )
            return 1

    # The TUI only works with an interactive terminal.
    try:
        if config.settings.boot_animation and sys.stdout.isatty():
            show_boot_animation(config, palette)
        app = ServerDeckApp(config, monitor=monitor, demo=args.demo)
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        Console(stderr=True).print(
            f"[bold red]ServerDeck crashed:[/] {type(exc).__name__}: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
