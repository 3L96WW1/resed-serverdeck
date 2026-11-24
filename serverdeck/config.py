"""Configuration loading and validation for ServerDeck."""

from __future__ import annotations

import getpass
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


class ConfigError(Exception):
    """Raised when a ServerDeck configuration cannot be used."""


def default_history_path() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path("~/.local/state").expanduser()
    )
    return root / "serverdeck" / "history.db"


@dataclass(frozen=True, slots=True)
class Thresholds:
    cpu: float = 80.0
    memory: float = 85.0
    disk: float = 90.0
    load_per_core: float = 1.25


@dataclass(frozen=True, slots=True)
class Settings:
    theme: Literal["graphite", "mono", "black", "midnight", "console"] = "mono"
    refresh_interval: float = 5.0
    auto_page: bool = True
    auto_page_interval: float = 6.0
    boot_animation: bool = True
    alerts: bool = True
    history: bool = True
    history_days: int = 7
    history_db: Path = field(default_factory=default_history_path)
    connect_timeout: float = 6.0
    command_timeout: float = 10.0
    history_points: int = 48
    known_hosts: Path = field(
        default_factory=lambda: Path("~/.ssh/known_hosts").expanduser()
    )
    thresholds: Thresholds = field(default_factory=Thresholds)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    id: str
    name: str
    transport: Literal["local", "ssh"]
    group: str = "Default Server Group"
    enabled: bool = True
    tags: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    host: str | None = None
    port: int = 22
    user: str | None = None
    password: str | None = field(default=None, repr=False)
    key: Path | None = None
    key_passphrase: str | None = field(default=None, repr=False)
    host_key_policy: Literal["tofu", "strict"] = "tofu"

    @property
    def endpoint(self) -> str:
        if self.transport == "local":
            return "localhost"
        return f"{self.host}:{self.port}"

    @property
    def login(self) -> str:
        if self.transport == "local":
            return getpass.getuser()
        return f"{self.user}@{self.host}"


@dataclass(frozen=True, slots=True)
class Config:
    path: Path
    settings: Settings
    servers: tuple[ServerConfig, ...]
    warnings: tuple[str, ...] = ()

    def server_by_id(self, server_id: str) -> ServerConfig:
        for server in self.servers:
            if server.id == server_id:
                return server
        raise KeyError(server_id)


DEFAULT_SETTINGS = Settings()


def _expect_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where} must be a mapping/object")
    for key in value:
        if not isinstance(key, str):
            raise ConfigError(f"{where} contains a non-string key")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ConfigError(f"unknown key(s) in {where}: {names}")


def _number(
    value: Any,
    where: str,
    *,
    minimum: float,
    maximum: float,
    integer: bool = False,
) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        kind = "integer" if integer else "number"
        raise ConfigError(f"{where} must be a {kind}")
    if not minimum <= float(value) <= maximum:
        raise ConfigError(f"{where} must be between {minimum} and {maximum}")
    if integer:
        if int(value) != value:
            raise ConfigError(f"{where} must be an integer")
        return int(value)
    return float(value)


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where} must be true or false")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a string")
    return value.strip()


def _string_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{where} must be a list of strings")
    cleaned = tuple(item.strip() for item in value if item.strip())
    return tuple(dict.fromkeys(cleaned))


def _slugify(name: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or fallback


def _parse_settings(raw: Any) -> Settings:
    data = _expect_mapping(raw, "settings")
    allowed = {
        "theme",
        "refresh_interval",
        "auto_page",
        "auto_page_interval",
        "boot_animation",
        "alerts",
        "history",
        "history_days",
        "history_db",
        "connect_timeout",
        "command_timeout",
        "history_points",
        "known_hosts",
        "thresholds",
    }
    _reject_unknown(data, allowed, "settings")

    default = DEFAULT_SETTINGS
    theme = _string(data.get("theme", default.theme), "settings.theme").lower()
    if theme not in {"graphite", "mono", "black", "midnight", "console"}:
        raise ConfigError(
            "settings.theme must be 'graphite', 'mono', 'black', 'midnight', or 'console'"
        )
    refresh = _number(
        data.get("refresh_interval", default.refresh_interval),
        "settings.refresh_interval",
        minimum=1,
        maximum=3600,
    )
    auto_page = _boolean(data.get("auto_page", default.auto_page), "settings.auto_page")
    auto_page_interval = _number(
        data.get("auto_page_interval", default.auto_page_interval),
        "settings.auto_page_interval",
        minimum=1,
        maximum=3600,
    )
    boot_animation = _boolean(
        data.get("boot_animation", default.boot_animation),
        "settings.boot_animation",
    )
    alerts = _boolean(data.get("alerts", default.alerts), "settings.alerts")
    history = _boolean(data.get("history", default.history), "settings.history")
    history_days = _number(
        data.get("history_days", default.history_days),
        "settings.history_days",
        minimum=1,
        maximum=365,
        integer=True,
    )
    history_db_str = _string(
        data.get("history_db", str(default.history_db)), "settings.history_db"
    )
    if not history_db_str:
        raise ConfigError("settings.history_db cannot be empty")
    connect = _number(
        data.get("connect_timeout", default.connect_timeout),
        "settings.connect_timeout",
        minimum=0.5,
        maximum=120,
    )
    command = _number(
        data.get("command_timeout", default.command_timeout),
        "settings.command_timeout",
        minimum=1,
        maximum=300,
    )
    history_points = _number(
        data.get("history_points", default.history_points),
        "settings.history_points",
        minimum=8,
        maximum=300,
        integer=True,
    )

    known_hosts_raw = data.get("known_hosts", "~/.ssh/known_hosts")
    known_hosts_str = _string(known_hosts_raw, "settings.known_hosts")
    if not known_hosts_str:
        raise ConfigError("settings.known_hosts cannot be empty")

    thresholds_raw = _expect_mapping(data.get("thresholds"), "settings.thresholds")
    _reject_unknown(
        thresholds_raw,
        {"cpu", "memory", "disk", "load_per_core"},
        "settings.thresholds",
    )
    thresholds = Thresholds(
        cpu=float(
            _number(
                thresholds_raw.get("cpu", 80),
                "settings.thresholds.cpu",
                minimum=1,
                maximum=100,
            )
        ),
        memory=float(
            _number(
                thresholds_raw.get("memory", 85),
                "settings.thresholds.memory",
                minimum=1,
                maximum=100,
            )
        ),
        disk=float(
            _number(
                thresholds_raw.get("disk", 90),
                "settings.thresholds.disk",
                minimum=1,
                maximum=100,
            )
        ),
        load_per_core=float(
            _number(
                thresholds_raw.get("load_per_core", 1.25),
                "settings.thresholds.load_per_core",
                minimum=0.1,
                maximum=100,
            )
        ),
    )

    return Settings(
        theme=theme,  # type: ignore[arg-type]
        refresh_interval=float(refresh),
        auto_page=auto_page,
        auto_page_interval=float(auto_page_interval),
        boot_animation=boot_animation,
        alerts=alerts,
        history=history,
        history_days=int(history_days),
        history_db=Path(history_db_str).expanduser(),
        connect_timeout=float(connect),
        command_timeout=float(command),
        history_points=int(history_points),
        known_hosts=Path(known_hosts_str).expanduser(),
        thresholds=thresholds,
    )


def _secret(
    raw: Mapping[str, Any],
    direct_key: str,
    env_key: str,
    where: str,
) -> str | None:
    direct = raw.get(direct_key)
    env_name = raw.get(env_key)
    if direct is not None and env_name is not None:
        raise ConfigError(f"{where}: use either {direct_key} or {env_key}, not both")
    if env_name is not None:
        env_name = _string(env_name, f"{where}.{env_key}")
        if not env_name:
            raise ConfigError(f"{where}.{env_key} cannot be empty")
        value = os.environ.get(env_name)
        if value is None or value == "":
            raise ConfigError(
                f"{where}.{env_key} refers to unset/empty environment variable {env_name!r}"
            )
        return value
    if direct is not None:
        value = _string(direct, f"{where}.{direct_key}")
        return value or None
    return None


def _parse_server(raw: Any, index: int) -> ServerConfig:
    where = f"servers[{index}]"
    data = _expect_mapping(raw, where)
    allowed = {
        "id",
        "name",
        "type",
        "host",
        "port",
        "user",
        "password",
        "password_env",
        "key",
        "key_passphrase",
        "key_passphrase_env",
        "host_key_policy",
        "tags",
        "services",
        "group",
        "enabled",
    }
    _reject_unknown(data, allowed, where)

    name = _string(data.get("name"), f"{where}.name")
    if not name:
        raise ConfigError(f"{where}.name cannot be empty")

    raw_id = data.get("id")
    if raw_id is None:
        server_id = _slugify(name, f"server-{index + 1}")
    else:
        server_id = _string(raw_id, f"{where}.id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", server_id):
            raise ConfigError(
                f"{where}.id must use lowercase letters, digits, '-' or '_'"
            )

    host_value = data.get("host")
    raw_type = data.get("type")
    if raw_type is None:
        transport = "ssh" if host_value is not None else "local"
    else:
        transport = _string(raw_type, f"{where}.type").lower()
    if transport not in {"local", "ssh"}:
        raise ConfigError(f"{where}.type must be 'local' or 'ssh'")

    group = _string(data.get("group", "Default Server Group"), f"{where}.group")
    if not group:
        group = "Default Server Group"
    enabled = _boolean(data.get("enabled", True), f"{where}.enabled")
    tags = _string_list(data.get("tags"), f"{where}.tags")
    services = _string_list(data.get("services"), f"{where}.services")
    if len(services) > 24:
        raise ConfigError(f"{where}.services supports at most 24 entries")

    if transport == "local":
        if host_value not in (None, ""):
            raise ConfigError(f"{where}: local server must not define host")
        if data.get("port") not in (None, 22):
            raise ConfigError(f"{where}: local server must not define port")
        ssh_only_fields = (
            "user",
            "password",
            "password_env",
            "key",
            "key_passphrase",
            "key_passphrase_env",
            "host_key_policy",
        )
        if any(data.get(key) not in (None, "") for key in ssh_only_fields):
            raise ConfigError(f"{where}: local server must not define SSH credentials")
        return ServerConfig(
            id=server_id,
            name=name,
            transport="local",
            group=group,
            enabled=enabled,
            tags=tags,
            services=services,
        )

    host = _string(host_value, f"{where}.host")
    if not host:
        raise ConfigError(f"{where}.host is required for SSH servers")
    port = int(
        _number(
            data.get("port", 22),
            f"{where}.port",
            minimum=1,
            maximum=65535,
            integer=True,
        )
    )
    user_value = data.get("user", getpass.getuser())
    user = _string(user_value, f"{where}.user")
    if not user:
        raise ConfigError(f"{where}.user cannot be empty")

    password = _secret(data, "password", "password_env", where)
    passphrase = _secret(data, "key_passphrase", "key_passphrase_env", where)

    key: Path | None = None
    if data.get("key") is not None:
        key_str = _string(data["key"], f"{where}.key")
        if not key_str:
            raise ConfigError(f"{where}.key cannot be empty")
        key = Path(key_str).expanduser()
        if not key.is_file():
            raise ConfigError(f"{where}.key does not exist or is not a file: {key}")

    policy = _string(
        data.get("host_key_policy", "tofu"), f"{where}.host_key_policy"
    ).lower()
    if policy not in {"tofu", "strict"}:
        raise ConfigError(
            f"{where}.host_key_policy must be 'tofu' (trust on first use) or 'strict'"
        )

    return ServerConfig(
        id=server_id,
        name=name,
        transport="ssh",
        group=group,
        enabled=enabled,
        tags=tags,
        services=services,
        host=host,
        port=port,
        user=user,
        password=password,
        key=key,
        key_passphrase=passphrase,
        host_key_policy=policy,  # type: ignore[arg-type]
    )


def _permission_warning(path: Path, servers: tuple[ServerConfig, ...]) -> str | None:
    if not any(server.password or server.key_passphrase for server in servers):
        return None
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if mode & 0o077:
        return (
            f"{path} contains a plaintext credential and is readable by other users; "
            "run `chmod 600` on it or use password_env/key_passphrase_env"
        )
    return None


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate a YAML config from an explicit or conventional path."""

    config_path = find_config_path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        detail = getattr(exc, "problem", None) or str(exc)
        location = f" (line {mark.line + 1})" if mark is not None else ""
        raise ConfigError(f"invalid YAML in {config_path}{location}: {detail}") from exc

    root = _expect_mapping(raw, "configuration")
    _reject_unknown(root, {"version", "settings", "servers"}, "configuration")
    version = root.get("version", 1)
    if version != 1:
        raise ConfigError(f"unsupported configuration version {version!r}; expected 1")

    settings = _parse_settings(root.get("settings"))

    servers_raw = root.get("servers")
    if not isinstance(servers_raw, list) or not servers_raw:
        raise ConfigError("servers must be a non-empty list")

    servers = tuple(
        _parse_server(server_raw, index) for index, server_raw in enumerate(servers_raw)
    )
    ids = [server.id for server in servers]
    duplicates = sorted({server_id for server_id in ids if ids.count(server_id) > 1})
    if duplicates:
        raise ConfigError(f"duplicate server id(s): {', '.join(duplicates)}")
    names = [server.name for server in servers]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ConfigError(f"duplicate server name(s): {', '.join(duplicate_names)}")
    if sum(server.transport == "local" for server in servers) > 1:
        raise ConfigError("only one local server may be configured")

    warnings: list[str] = []
    warning = _permission_warning(config_path, servers)
    if warning:
        warnings.append(warning)

    return Config(
        path=config_path,
        settings=settings,
        servers=servers,
        warnings=tuple(warnings),
    )


def find_config_path(path: str | Path | None = None) -> Path:
    """Resolve the config path, following ServerDeck's search order."""

    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise ConfigError(f"config file not found: {candidate}")
        return candidate

    env_path = os.environ.get("SERVERDECK_CONFIG")
    if env_path:
        candidate = Path(env_path).expanduser()
        if not candidate.is_file():
            raise ConfigError(
                f"SERVERDECK_CONFIG points to a missing file: {candidate}"
            )
        return candidate

    xdg_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    candidates = [
        Path.cwd() / "serverdeck.yaml",
        Path.cwd() / "serverdeck.yml",
        xdg_home / "serverdeck" / "config.yaml",
        Path("/etc/serverdeck/config.yaml"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigError(
        "no config file found. Searched:\n  "
        f"{searched}\n"
        "Copy config.example.yaml to serverdeck.yaml or pass --config PATH."
    )
