from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from serverdeck.config import ConfigError, find_config_path, load_config


@pytest.fixture(autouse=True)
def _default_ssh_env(monkeypatch):
    monkeypatch.setenv("TEST_SSH_PASSWORD", "test-password")


def write_config(tmp_path: Path, data: dict, *, mode: int = 0o600) -> Path:
    path = tmp_path / "serverdeck.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    path.chmod(mode)
    return path


def base_config(**server_overrides):
    local = {"name": "local-box", "type": "local", "services": ["ssh"]}
    remote = {
        "name": "web-01",
        "type": "ssh",
        "host": "192.0.2.10",
        "user": "deploy",
        "password_env": "TEST_SSH_PASSWORD",
    }
    remote.update(server_overrides)
    return {
        "version": 1,
        "settings": {"refresh_interval": 3, "history_points": 24},
        "servers": [local, remote],
    }


def test_load_config_and_resolve_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_SSH_PASSWORD", "s3cret")
    path = write_config(tmp_path, base_config())
    config = load_config(path)
    assert config.path == path
    assert config.settings.refresh_interval == 3
    assert config.settings.history_points == 24
    assert config.settings.auto_page is True
    assert config.settings.auto_page_interval == 6
    assert config.settings.boot_animation is True
    assert config.settings.alerts is True
    assert config.settings.history is True
    assert config.settings.history_days == 7
    assert len(config.servers) == 2
    remote = config.servers[1]
    assert remote.password == "s3cret"
    assert remote.host_key_policy == "tofu"
    assert "s3cret" not in repr(remote)


def test_missing_password_env_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_SSH_PASSWORD", raising=False)
    path = write_config(tmp_path, base_config())
    with pytest.raises(ConfigError, match="unset/empty environment variable"):
        load_config(path)


def test_direct_password_warns_if_world_readable(tmp_path):
    data = base_config()
    data["servers"][1].pop("password_env")
    data["servers"][1]["password"] = "plain"
    path = write_config(tmp_path, data, mode=0o644)
    config = load_config(path)
    assert config.warnings
    assert "plaintext credential" in config.warnings[0]


def test_secret_env_must_be_string(tmp_path):
    data = base_config(password_env=123)
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="password_env must be a string"):
        load_config(path)


def test_password_and_password_env_are_mutually_exclusive(tmp_path):
    data = base_config(password="inline")
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="either password or password_env"):
        load_config(path)


def test_unknown_key_is_rejected(tmp_path):
    data = base_config()
    data["servers"][1]["typo"] = "x"
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(path)


def test_duplicate_server_ids_are_rejected(tmp_path):
    data = base_config()
    data["servers"][1]["id"] = "local-box"
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="duplicate server id"):
        load_config(path)


def test_only_one_local_server(tmp_path):
    data = base_config()
    data["servers"].append({"name": "another-local", "type": "local"})
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="only one local"):
        load_config(path)


def test_local_server_cannot_have_ssh_auth(tmp_path):
    data = base_config()
    data["servers"][0]["password_env"] = "X"
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="must not define SSH credentials"):
        load_config(path)


def test_server_type_is_inferred(tmp_path):
    data = {
        "servers": [
            {"name": "local"},
            {
                "name": "remote",
                "host": "192.0.2.25",
                "user": "root",
            },
        ]
    }
    path = write_config(tmp_path, data)
    config = load_config(path)
    assert [server.transport for server in config.servers] == ["local", "ssh"]
    assert config.servers[1].port == 22


def test_missing_key_file_is_rejected(tmp_path):
    data = {
        "servers": [
            {
                "name": "remote",
                "host": "192.0.2.25",
                "user": "root",
                "key": str(tmp_path / "nope"),
            }
        ]
    }
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(path)


def test_invalid_schedule_values(tmp_path):
    data = base_config()
    data["settings"]["refresh_interval"] = 0
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="between"):
        load_config(path)


def test_find_config_uses_env(tmp_path, monkeypatch):
    path = write_config(tmp_path, {"servers": [{"name": "local"}]})
    monkeypatch.setenv("SERVERDECK_CONFIG", str(path))
    assert find_config_path() == path


def test_find_config_missing_explicit_path(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        find_config_path(tmp_path / "missing.yaml")


def test_password_not_in_repr(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_SSH_PASSWORD", "top-secret")
    config = load_config(write_config(tmp_path, base_config()))
    assert "top-secret" not in repr(config)
    assert "top-secret" not in str(config)


def test_environment_is_not_mutated(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_SSH_PASSWORD", "secret")
    before = dict(os.environ)
    load_config(write_config(tmp_path, base_config()))
    assert dict(os.environ) == before


def test_theme_defaults_to_mono(tmp_path):
    path = write_config(tmp_path, base_config())
    assert load_config(path).settings.theme == "mono"


def test_midnight_theme_can_be_selected(tmp_path):
    data = base_config()
    data["settings"]["theme"] = "midnight"
    path = write_config(tmp_path, data)
    assert load_config(path).settings.theme == "midnight"


def test_invalid_theme_is_rejected(tmp_path):
    data = base_config()
    data["settings"]["theme"] = "light"
    path = write_config(tmp_path, data)
    with pytest.raises(ConfigError, match="theme must be"):
        load_config(path)


def test_auto_page_and_boot_settings(tmp_path):
    data = base_config()
    data["settings"].update(
        {
            "auto_page": False,
            "auto_page_interval": 12,
            "boot_animation": False,
        }
    )
    config = load_config(write_config(tmp_path, data))
    assert config.settings.auto_page is False
    assert config.settings.auto_page_interval == 12
    assert config.settings.boot_animation is False


def test_auto_page_interval_must_be_valid(tmp_path):
    data = base_config()
    data["settings"]["auto_page_interval"] = 0
    with pytest.raises(ConfigError, match="settings.auto_page_interval"):
        load_config(write_config(tmp_path, data))


def test_auto_page_must_be_boolean(tmp_path):
    data = base_config()
    data["settings"]["auto_page"] = 1
    with pytest.raises(ConfigError, match="settings.auto_page must be true or false"):
        load_config(write_config(tmp_path, data))


def test_server_group_defaults_to_english_name(tmp_path):
    config = load_config(write_config(tmp_path, base_config()))
    assert config.servers[0].group == "Default Server Group"
    assert config.servers[1].group == "Default Server Group"


def test_custom_server_group(tmp_path):
    data = base_config()
    data["servers"][1]["group"] = "Production Web"
    config = load_config(write_config(tmp_path, data))
    assert config.servers[1].group == "Production Web"


def test_alerts_can_be_disabled(tmp_path):
    data = base_config()
    data["settings"]["alerts"] = False
    assert load_config(write_config(tmp_path, data)).settings.alerts is False


def test_history_settings_can_be_customized(tmp_path):
    data = base_config()
    data["settings"].update(
        {"history": False, "history_days": 3, "history_db": "/tmp/sd-history.db"}
    )
    config = load_config(write_config(tmp_path, data))
    assert config.settings.history is False
    assert config.settings.history_days == 3
    assert str(config.settings.history_db) == "/tmp/sd-history.db"


def test_disabled_server_is_placeholder_without_credentials(tmp_path):
    data = base_config()
    data["servers"][1] = {
        "name": "puzzlebox",
        "type": "ssh",
        "host": "192.0.2.222",
        "enabled": False,
        "group": "Lab",
    }
    config = load_config(write_config(tmp_path, data))
    placeholder = config.servers[1]
    assert placeholder.enabled is False
    assert placeholder.password is None
    assert placeholder.key is None
    assert placeholder.group == "Lab"
