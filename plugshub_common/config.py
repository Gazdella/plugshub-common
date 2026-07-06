"""Typed, fail-fast configuration loader (SaaS Constitution Article III).

Configuration is typed and loaded through the shared library, and it MUST fail fast: a missing or
insecure required value aborts startup (§1). There are **no insecure defaults in code** (§1); no
host, IP, URL, or credential is hardcoded (§3); real secrets come from the environment or a managed
secret store (§4).

This wraps ``pydantic-settings`` so every service subclasses one base with a consistent environment
prefix, and turns validation failures into a single, clear startup abort. ``pydantic`` /
``pydantic-settings`` are imported lazily so a service that does not use this module is unaffected.
"""

import os
from typing import Any, Type, TypeVar

__all__ = ["BaseServiceSettings", "load_settings", "ConfigError", "require_env"]


class ConfigError(RuntimeError):
    """A configuration failure that MUST abort startup (Article III §1)."""


def _import_settings_base() -> Any:
    try:
        from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via error path only
        raise ConfigError(
            "pydantic-settings is required for plugshub_common.config; "
            "install plugshub-common[config]"
        ) from exc
    return BaseSettings, SettingsConfigDict


_BaseSettings, _SettingsConfigDict = _import_settings_base()


class BaseServiceSettings(_BaseSettings):  # type: ignore[misc, valid-type]
    """Base settings every service subclasses (Article III).

    Reads from the process environment (and, in development only, a ``.env`` file). Unknown keys are
    ignored; a declared-but-missing required field aborts startup via :func:`load_settings`. Declare
    required secrets with **no default** so their absence is fatal — never give a secret a fallback
    value in code (§1).
    """

    model_config = _SettingsConfigDict(
        env_file=os.getenv("PLUGSHUB_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


T = TypeVar("T", bound=BaseServiceSettings)


def load_settings(settings_cls: Type[T]) -> T:
    """Instantiate and validate a settings class, aborting startup on any failure (Article III §1).

    Wraps pydantic's ``ValidationError`` in :class:`ConfigError` with a readable summary so a
    missing required value produces one clear "cannot start" message rather than a stack trace.
    """
    try:
        return settings_cls()
    except Exception as exc:  # noqa: BLE001 - fail fast, convert to a single abort
        raise ConfigError(
            "invalid configuration for {}: {}".format(settings_cls.__name__, exc)
        ) from exc


def require_env(name: str) -> str:
    """Fetch a required environment variable, aborting if it is missing or empty (Article III §1).

    A convenience for the rare non-pydantic call site (e.g. bootstrapping before settings load). No
    default is permitted — that is the point (§1).
    """
    value = os.getenv(name)
    if value is None or value == "":
        raise ConfigError("required environment variable {} is not set".format(name))
    return value
