from typing import Optional

import pytest

from plugshub_common.config import BaseServiceSettings, ConfigError, load_settings, require_env


class DemoSettings(BaseServiceSettings):
    service_name: str
    port: int = 8000
    internal_service_token: Optional[str] = None


def test_loads_from_env(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "demo")
    monkeypatch.setenv("PORT", "9001")
    settings = load_settings(DemoSettings)
    assert settings.service_name == "demo" and settings.port == 9001


def test_missing_required_aborts(monkeypatch):
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    # Ensure no stray .env supplies it.
    monkeypatch.setenv("PLUGSHUB_ENV_FILE", "/nonexistent/.env")
    with pytest.raises(ConfigError):
        load_settings(DemoSettings)


def test_require_env(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "value")
    assert require_env("MY_SECRET") == "value"
    monkeypatch.delenv("MY_SECRET", raising=False)
    with pytest.raises(ConfigError):
        require_env("MY_SECRET")


def test_require_env_empty_is_missing(monkeypatch):
    monkeypatch.setenv("EMPTY", "")
    with pytest.raises(ConfigError):
        require_env("EMPTY")
