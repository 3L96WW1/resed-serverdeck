"""Agentless metric collection over the local shell or SSH.

A single POSIX shell probe is executed locally or through SSH.  It reads
``/proc`` and standard Linux utilities and returns a compact key=value
document.  SSH connections are kept alive between refresh cycles, so only
the first poll pays the full handshake cost.
"""

from __future__ import annotations

import contextlib
import getpass
import math
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import paramiko

from .config import ServerConfig, Settings
from .models import HostMetrics, ServiceState


class CollectionError(RuntimeError):
    """A host could not be queried or returned unusable data."""


@dataclass(frozen=True, slots=True)
class Collection:
    metrics: HostMetrics
    poll_ms: float


_SCRIPT = r"""
export LC_ALL=C LANG=C
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

printf 'hostname=%s\n' "$(hostname 2>/dev/null || uname -n 2>/dev/null || echo unknown)"
OS_NAME="Linux"
if [ -r /etc/os-release ]; then
    . /etc/os-release
    if [ -n "${PRETTY_NAME:-}" ]; then OS_NAME="$PRETTY_NAME"; fi
fi
printf 'os=%s\n' "$OS_NAME"
printf 'kernel=%s\n' "$(uname -r 2>/dev/null || echo unknown)"
printf 'arch=%s\n' "$(uname -m 2>/dev/null || echo unknown)"
printf 'cpu_count=%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"

UPTIME=0
if [ -r /proc/uptime ]; then read -r UPTIME _ < /proc/uptime 2>/dev/null || true; fi
printf 'uptime_seconds=%s\n' "${UPTIME:-0}"

LOAD1=0; LOAD5=0; LOAD15=0
if [ -r /proc/loadavg ]; then read -r LOAD1 LOAD5 LOAD15 _ < /proc/loadavg 2>/dev/null || true; fi
printf 'load1=%s\nload5=%s\nload15=%s\n' "${LOAD1:-0}" "${LOAD5:-0}" "${LOAD15:-0}"

CPU_PRINTED=0
if [ -r /proc/stat ]; then
    read -r _ U1 N1 S1 I1 W1 Q1 SQ1 ST1 _ < /proc/stat 2>/dev/null || true
    sleep 0.20
    read -r _ U2 N2 S2 I2 W2 Q2 SQ2 ST2 _ < /proc/stat 2>/dev/null || true
    if [ -n "${U2:-}" ]; then
        awk -v u1="${U1:-0}" -v n1="${N1:-0}" -v s1="${S1:-0}" -v i1="${I1:-0}" -v w1="${W1:-0}" -v q1="${Q1:-0}" -v sq1="${SQ1:-0}" -v st1="${ST1:-0}" \
            -v u2="${U2:-0}" -v n2="${N2:-0}" -v s2="${S2:-0}" -v i2="${I2:-0}" -v w2="${W2:-0}" -v q2="${Q2:-0}" -v sq2="${SQ2:-0}" -v st2="${ST2:-0}" \
            'BEGIN {
                t1=u1+n1+s1+i1+w1+q1+sq1+st1; t2=u2+n2+s2+i2+w2+q2+sq2+st2;
                dt=t2-t1; di=(i2+w2)-(i1+w1); pct=0;
                if (dt > 0) pct=100*(dt-di)/dt;
                if (pct < 0) pct=0; if (pct > 100) pct=100;
                printf "cpu_percent=%.2f\n", pct;
            }'
        CPU_PRINTED=1
    fi
fi
[ "$CPU_PRINTED" = 1 ] || { printf 'cpu_percent=0\n'; }

if [ -r /proc/meminfo ]; then
    awk '
        /^MemTotal:/ { mt=$2 }
        /^MemAvailable:/ { ma=$2 }
        /^MemFree:/ { mf=$2 }
        /^Buffers:/ { mb=$2 }
        /^Cached:/ { mc=$2 }
        /^SwapTotal:/ { st=$2 }
        /^SwapFree:/ { sf=$2 }
        END {
            if (ma == "") ma=mf+mb+mc;
            used=mt-ma; if (used < 0) used=0;
            swap_used=st-sf; if (swap_used < 0) swap_used=0;
            printf "memory_total_bytes=%.0f\n", mt*1024;
            printf "memory_used_bytes=%.0f\n", used*1024;
            printf "swap_total_bytes=%.0f\n", st*1024;
            printf "swap_used_bytes=%.0f\n", swap_used*1024;
        }' /proc/meminfo
fi

DF_OUT=$(df -Pk / 2>/dev/null | awk 'NR==2 { printf "disk_total_bytes=%.0f\ndisk_used_bytes=%.0f\n", $2*1024, $3*1024 }')
if [ -n "$DF_OUT" ]; then printf '%s\n' "$DF_OUT"; else printf 'disk_total_bytes=0\ndisk_used_bytes=0\n'; fi

PROC_COUNT=$(ps -e 2>/dev/null | awk 'NR > 1 { n++ } END { print n+0 }')
printf 'process_count=%s\n' "${PROC_COUNT:-0}"

awk '
    NR > 1 {
        line=$0; sub(/^[ \t]+/, "", line); split(line, parts, ":");
        if (parts[1] != "lo") {
            sub(/^[ \t]+/, "", parts[2]);
            split(parts[2], values, /[ \t]+/);
            rx += values[1]; tx += values[9];
        }
    }
    END { printf "net_rx_total_bytes=%.0f\nnet_tx_total_bytes=%.0f\n", rx, tx }
' /proc/net/dev 2>/dev/null

SERVICE_INDEX=0
for SERVICE in __SERVICES__; do
    STATE="unavailable"
    if command -v systemctl >/dev/null 2>&1; then
        STATE=$(systemctl is-active "$SERVICE" 2>/dev/null || true)
        if [ -z "$STATE" ]; then STATE="unknown"; fi
    fi
    printf 'service.%s.name=%s\n' "$SERVICE_INDEX" "$SERVICE"
    printf 'service.%s.state=%s\n' "$SERVICE_INDEX" "$STATE"
    SERVICE_INDEX=$((SERVICE_INDEX + 1))
done
"""


def build_script(services: Iterable[str]) -> str:
    values = " ".join(shlex.quote(service) for service in services)
    return _SCRIPT.replace("__SERVICES__", values)


INT_FIELDS = {
    "cpu_count": 1,
    "memory_total_bytes": 0,
    "memory_used_bytes": 0,
    "swap_total_bytes": 0,
    "swap_used_bytes": 0,
    "disk_total_bytes": 0,
    "disk_used_bytes": 0,
    "process_count": 0,
    "net_rx_total_bytes": 0,
    "net_tx_total_bytes": 0,
}
FLOAT_FIELDS = (
    "uptime_seconds",
    "load1",
    "load5",
    "load15",
    "cpu_percent",
)
REQUIRED_FIELDS = {
    "hostname",
    "os",
    "kernel",
    "arch",
    *INT_FIELDS,
    *FLOAT_FIELDS,
}


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _safe_value(text: str, limit: int = 200) -> str:
    """Strip terminal control characters from untrusted remote strings."""

    return _CONTROL_CHARS.sub("", text).strip()[:limit]


def _clean_error(text: str, limit: int = 500) -> str:
    text = _safe_value(text, limit=limit * 2)
    text = " ".join(text.split())
    return text[:limit] if text else "no error output"


def parse_probe(output: str) -> HostMetrics:
    values: dict[str, str] = {}
    services: dict[str, dict[str, str]] = {}

    for raw_line in output.splitlines():
        if not raw_line or "=" not in raw_line:
            continue
        key, _, value = raw_line.partition("=")
        if key.startswith("service."):
            _, index, field = key.split(".", 2)
            services.setdefault(index, {})[field] = value
        else:
            values[key] = value

    missing = sorted(REQUIRED_FIELDS - values.keys())
    if missing:
        raise CollectionError(
            "probe returned incomplete data (missing: " + ", ".join(missing) + ")"
        )

    def as_int(key: str) -> int:
        try:
            return max(0, int(float(values[key])))
        except (TypeError, ValueError) as exc:
            raise CollectionError(
                f"invalid integer for {key}: {values[key]!r}"
            ) from exc

    def as_float(key: str) -> float:
        try:
            number = float(values[key])
        except (TypeError, ValueError) as exc:
            raise CollectionError(f"invalid number for {key}: {values[key]!r}") from exc
        if not math.isfinite(number):
            raise CollectionError(f"non-finite number for {key}")
        return number

    service_states: list[ServiceState] = []
    for index in sorted(services, key=lambda item: int(item) if item.isdigit() else 0):
        item = services[index]
        name = _safe_value(item.get("name", ""), 128)
        state = _safe_value(item.get("state", "unknown"), 32) or "unknown"
        if name:
            service_states.append(ServiceState(name=name, state=state))

    cpu_count = max(1, as_int("cpu_count"))
    return HostMetrics(
        hostname=_safe_value(values["hostname"], 255) or "unknown",
        os_name=_safe_value(values["os"], 160) or "Linux",
        kernel=_safe_value(values["kernel"], 120) or "unknown",
        arch=_safe_value(values["arch"], 64) or "unknown",
        uptime_seconds=max(0.0, as_float("uptime_seconds")),
        cpu_count=cpu_count,
        cpu_percent=min(100.0, max(0.0, as_float("cpu_percent"))),
        load1=max(0.0, as_float("load1")),
        load5=max(0.0, as_float("load5")),
        load15=max(0.0, as_float("load15")),
        memory_total=as_int("memory_total_bytes"),
        memory_used=as_int("memory_used_bytes"),
        swap_total=as_int("swap_total_bytes"),
        swap_used=as_int("swap_used_bytes"),
        disk_total=as_int("disk_total_bytes"),
        disk_used=as_int("disk_used_bytes"),
        process_count=as_int("process_count"),
        net_rx_total=as_int("net_rx_total_bytes"),
        net_tx_total=as_int("net_tx_total_bytes"),
        services=tuple(service_states),
        sampled_at=datetime.now(timezone.utc),
    )


class Collector(Protocol):
    def collect(self) -> Collection: ...

    def close(self) -> None: ...


class LocalCollector:
    """Run the probe on this machine without any external dependency."""

    def __init__(self, server: ServerConfig, settings: Settings) -> None:
        self.server = server
        self.settings = settings

    def collect(self) -> Collection:
        script = build_script(self.server.services)
        started = time.perf_counter()
        env = os.environ.copy()
        env.update({"LC_ALL": "C", "LANG": "C"})
        try:
            completed = subprocess.run(
                ["/bin/sh", "-c", script],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.settings.command_timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CollectionError(
                f"local probe timed out after {self.settings.command_timeout:g}s"
            ) from exc
        except OSError as exc:
            raise CollectionError(f"cannot run local probe: {exc}") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        if completed.returncode != 0:
            raise CollectionError(
                "local probe failed: " + _clean_error(completed.stderr)
            )
        return Collection(metrics=parse_probe(completed.stdout), poll_ms=elapsed_ms)

    def close(self) -> None:
        return None


_KNOWN_HOSTS_LOCK = threading.Lock()


class _TrustOnFirstUsePolicy(paramiko.MissingHostKeyPolicy):
    """Accept an unknown host key once and remember that it was added.

    Unlike Paramiko's AutoAddPolicy this does not write known_hosts during
    the handshake.  The collector persists the key after a successful login,
    under a process-wide lock.
    """

    def __init__(self) -> None:
        self.added: list[tuple[str, str, paramiko.PKey]] = []

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        client.get_host_keys().add(hostname, key.get_name(), key)
        self.added.append((hostname, key.get_name(), key))


class SSHCollector:
    """Persistent Paramiko connection with password, key, and agent auth."""

    def __init__(self, server: ServerConfig, settings: Settings) -> None:
        self.server = server
        self.settings = settings
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()

    def _new_client(self) -> tuple[paramiko.SSHClient, _TrustOnFirstUsePolicy | None]:
        client = paramiko.SSHClient()
        known_hosts: Path = self.settings.known_hosts
        if known_hosts.is_file():
            try:
                client.load_host_keys(str(known_hosts))
            except (OSError, paramiko.SSHException) as exc:
                raise CollectionError(
                    f"cannot read known_hosts file {known_hosts}: {exc}"
                ) from exc
        policy: _TrustOnFirstUsePolicy | None = None
        if self.server.host_key_policy == "strict":
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            # Trust on first use: unknown keys are accepted once and persisted.
            # A changed key for an already known host is still rejected.
            policy = _TrustOnFirstUsePolicy()
            client.set_missing_host_key_policy(policy)
        return client, policy

    def _connect(self) -> paramiko.SSHClient:
        client, policy = self._new_client()
        kwargs: dict[str, object] = {
            "hostname": self.server.host or "",
            "port": self.server.port,
            "username": self.server.user,
            "timeout": self.settings.connect_timeout,
            "banner_timeout": self.settings.connect_timeout,
            "auth_timeout": self.settings.connect_timeout,
            "compress": True,
        }
        if self.server.key is not None:
            kwargs["key_filename"] = str(self.server.key)
        if self.server.password:
            kwargs["password"] = self.server.password
        if self.server.key_passphrase:
            kwargs["passphrase"] = self.server.key_passphrase
        if not self.server.password and self.server.key is None:
            kwargs["allow_agent"] = True
            kwargs["look_for_keys"] = True
        else:
            kwargs["allow_agent"] = False
            kwargs["look_for_keys"] = False

        try:
            client.connect(**kwargs)  # type: ignore[arg-type]
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(30)
            if policy is not None and policy.added:
                self._persist_host_key(policy.added)
            return client
        except Exception:
            client.close()
            raise

    def _persist_host_key(self, added: list[tuple[str, str, paramiko.PKey]]) -> None:
        """Merge first-seen keys into known_hosts without losing parallel writes."""

        known_hosts = self.settings.known_hosts
        try:
            known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with _KNOWN_HOSTS_LOCK:
                merged = paramiko.HostKeys()
                if known_hosts.is_file():
                    merged.load(str(known_hosts))
                for hostname, keytype, key in added:
                    existing = merged.lookup(hostname)
                    if existing is not None:
                        previous = existing.get(keytype)
                        if previous is not None and previous.asbytes() != key.asbytes():
                            raise CollectionError(
                                f"host key for {hostname} changed while connecting; "
                                "refusing to overwrite known_hosts"
                            )
                    merged.add(hostname, keytype, key)
                fd, temp_name = tempfile.mkstemp(
                    prefix=known_hosts.name + ".",
                    suffix=".serverdeck.tmp",
                    dir=known_hosts.parent,
                )
                os.close(fd)
                temp_path = Path(temp_name)
                try:
                    merged.save(str(temp_path))
                    with contextlib.suppress(OSError):
                        temp_path.chmod(0o600)
                    temp_path.replace(known_hosts)
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
        except CollectionError:
            raise
        except Exception as exc:
            # If the first-seen key cannot be recorded, TOFU would silently
            # trust every future key. Refuse the connection instead.
            raise CollectionError(
                f"cannot persist host key to {known_hosts}: {_clean_error(str(exc))}"
            ) from exc

    def _alive(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return bool(transport and transport.is_active())

    def _ensure_client(self) -> tuple[paramiko.SSHClient, bool]:
        if self._alive():
            assert self._client is not None
            return self._client, True
        self.close()
        self._client = self._connect()
        return self._client, False

    def _run(self, script: str) -> str:
        client, _ = self._ensure_client()
        channel = None
        try:
            _, stdout, stderr = client.exec_command(
                script, timeout=self.settings.command_timeout
            )
            channel = stdout.channel
            channel.settimeout(self.settings.command_timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            exit_status = channel.recv_exit_status()
        except TimeoutError as exc:
            raise CollectionError(
                f"remote probe timed out after {self.settings.command_timeout:g}s"
            ) from exc
        except Exception:
            if channel is not None:
                channel.close()
            raise
        finally:
            if channel is not None:
                channel.close()

        if exit_status != 0:
            raise CollectionError(f"remote probe failed: {_clean_error(error)}")
        return output

    def collect(self) -> Collection:
        with self._lock:
            script = build_script(self.server.services)
            started = time.perf_counter()
            had_connection = self._alive()
            try:
                output = self._run(script)
            except Exception as exc:
                self.close()
                if had_connection and not isinstance(exc, CollectionError):
                    # A long-lived connection may have been dropped; reconnect
                    # once before declaring the node offline. Probe-level errors
                    # (timeouts, non-zero exit) are not retried.
                    try:
                        output = self._run(script)
                    except Exception as retry_exc:
                        self.close()
                        raise self._translate_error(retry_exc) from retry_exc
                else:
                    raise self._translate_error(exc) from exc

            elapsed_ms = (time.perf_counter() - started) * 1000
            return Collection(metrics=parse_probe(output), poll_ms=elapsed_ms)

    def _translate_error(self, exc: Exception) -> CollectionError:
        if isinstance(exc, CollectionError):
            return exc
        host = self.server.host or "host"
        user = self.server.user or getpass.getuser()
        if isinstance(exc, paramiko.AuthenticationException):
            return CollectionError(f"authentication failed for {user}@{host}")
        if isinstance(exc, paramiko.BadHostKeyException):
            return CollectionError(
                f"host key changed for {host}; refusing to connect (possible MITM)"
            )
        if isinstance(exc, TimeoutError):
            return CollectionError(
                f"connection to {host} timed out after "
                f"{self.settings.connect_timeout:g}s"
            )
        if isinstance(exc, paramiko.SSHException):
            message = str(exc)
            if "not found in known_hosts" in message:
                return CollectionError(
                    f"host key for {host} is unknown (strict policy); "
                    "add it to known_hosts or set host_key_policy: tofu"
                )
            return CollectionError(f"SSH error for {host}: {_clean_error(message)}")
        if isinstance(exc, OSError):
            return CollectionError(f"cannot reach {host}: {_clean_error(str(exc))}")
        return CollectionError(f"{type(exc).__name__}: {_clean_error(str(exc))}")

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


def make_collector(server: ServerConfig, settings: Settings) -> Collector:
    if server.transport == "local":
        return LocalCollector(server, settings)
    return SSHCollector(server, settings)
