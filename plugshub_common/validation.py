"""Boundary input validation on typed models (SaaS Constitution Article VI §5).

Input MUST be validated at the boundary with typed models; malformed input is rejected with the
error envelope (Article VI §5, Article V). This module decodes-then-validates at the edge so a
missing/garbage JSON body becomes ``common.invalid_body`` (400) and a well-formed-but-invalid body
becomes ``common.validation_error`` (422) — never an unhandled 500 (Article XVI §1).

``pydantic`` is imported lazily so ``import plugshub_common`` stays light. Field-level errors are
surfaced in ``details`` (Article V §5) without leaking internals.
"""

import json
from typing import Any, Dict, Type, TypeVar

from plugshub_common.errors import InvalidBodyError, ValidationFailedError

__all__ = ["parse_json_body", "validate_model", "field_errors"]

T = TypeVar("T")


def parse_json_body(raw: Any) -> Any:
    """Decode a raw request body to JSON, or raise :class:`InvalidBodyError` (Article XVI §1).

    An empty or non-JSON body is a client fault (400 ``common.invalid_body``), never a server fault.
    Accepts ``bytes``/``str``/already-parsed objects.
    """
    if raw is None or raw == b"" or raw == "":
        raise InvalidBodyError("request body is empty")
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidBodyError("request body is not valid JSON") from exc


def field_errors(exc: Exception) -> Dict[str, str]:
    """Flatten a pydantic ``ValidationError`` into ``{field_path: message}`` (Article V §5)."""
    details: Dict[str, str] = {}
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return details
    for err in errors():
        loc = err.get("loc", ())
        key = ".".join(str(part) for part in loc) or "__root__"
        details[key] = err.get("msg", "invalid")
    return details


def validate_model(model_cls: Type[T], data: Any) -> T:
    """Validate ``data`` against a pydantic model, raising the shared errors on failure.

    Malformed (non-mapping) input → :class:`InvalidBodyError` (400). A mapping that fails validation
    → :class:`ValidationFailedError` (422) with field-level ``details`` (Article VI §5, V §5).
    """
    try:
        from pydantic import BaseModel, ValidationError  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via error path only
        raise RuntimeError(
            "pydantic is required for plugshub_common.validation; install plugshub-common[config]"
        ) from exc

    if not isinstance(model_cls, type) or not issubclass(model_cls, BaseModel):
        raise TypeError("model_cls MUST be a pydantic BaseModel subclass")

    if not isinstance(data, dict):
        raise InvalidBodyError("request body must be a JSON object")

    try:
        # pydantic v2 uses ``model_validate``; v1 uses ``parse_obj``.
        validator = getattr(model_cls, "model_validate", None) or model_cls.parse_obj
        return validator(data)  # type: ignore[no-any-return]
    except ValidationError as exc:
        raise ValidationFailedError(
            "input validation failed", details=field_errors(exc)
        ) from exc
