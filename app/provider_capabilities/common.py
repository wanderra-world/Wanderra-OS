"""Shared canonical contracts for provider capability execution."""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Union, get_args, get_origin, get_type_hints


class CanonicalErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SCOPE = "scope"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    QUOTA = "quota"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"


class RetryClassification(StrEnum):
    NEVER = "never"
    BACKOFF = "backoff"
    REFRESH_AUTH = "refresh_auth"
    REFRESH_RESOURCE = "refresh_resource"


_RETRY_BY_CATEGORY = {
    CanonicalErrorCategory.AUTHENTICATION: RetryClassification.REFRESH_AUTH,
    CanonicalErrorCategory.AUTHORIZATION: RetryClassification.NEVER,
    CanonicalErrorCategory.SCOPE: RetryClassification.NEVER,
    CanonicalErrorCategory.RATE_LIMIT: RetryClassification.BACKOFF,
    CanonicalErrorCategory.TRANSIENT: RetryClassification.BACKOFF,
    CanonicalErrorCategory.CONFLICT: RetryClassification.REFRESH_RESOURCE,
    CanonicalErrorCategory.NOT_FOUND: RetryClassification.NEVER,
    CanonicalErrorCategory.INVALID_INPUT: RetryClassification.NEVER,
    CanonicalErrorCategory.QUOTA: RetryClassification.BACKOFF,
    CanonicalErrorCategory.UNSUPPORTED_CAPABILITY: RetryClassification.NEVER,
}


class ProviderCapabilityError(RuntimeError):
    """Safe provider-neutral error exposed across the SDK boundary."""

    def __init__(
        self,
        category: CanonicalErrorCategory,
        safe_message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        if not safe_message or len(safe_message) > 500:
            raise ValueError("A bounded safe canonical message is required.")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("Retry delay cannot be negative.")
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.retry = _RETRY_BY_CATEGORY[category]
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class OpaqueCursor:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("Cursor must be non-empty.")
        if len(self.value) > 4096:
            raise ValueError("Cursor exceeds the canonical size limit.")


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int = 100
    cursor: OpaqueCursor | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 1000:
            raise ValueError("Page limit must be between 1 and 1000.")


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: tuple[T, ...]
    next_cursor: OpaqueCursor | None = None


def _is_json(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (tuple, list)):
        return all(_is_json(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_json(item) for key, item in value.items())
    return False


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ExtensionEnvelope:
    """Namespaced, non-authoritative provider extension values."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if any("/" not in key for key in self.values):
            raise ValueError("Extension keys must be namespaced.")
        if not _is_json(self.values):
            raise TypeError("Extension values must be JSON-compatible.")
        object.__setattr__(self, "values", _freeze_json(self.values))


EMPTY_EXTENSIONS = ExtensionEnvelope({})


@dataclass(frozen=True, slots=True)
class VersionPrecondition:
    etag: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if (self.etag is None) == (self.version is None):
            raise ValueError("Provide exactly one version precondition.")
        if self.etag == "" or self.version == "":
            raise ValueError("Version precondition cannot be empty.")


@dataclass(frozen=True, slots=True)
class MutationContext:
    idempotency_key: str
    precondition: VersionPrecondition | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key or len(self.idempotency_key) > 255:
            raise ValueError("A bounded idempotency key is required.")


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    key: str
    version: int
    operations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.key or self.version < 1 or not self.operations:
            raise ValueError("Capability key, positive version, and operations are required.")
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("Capability operations must be unique.")


@dataclass(frozen=True, slots=True)
class NegotiatedCapabilities:
    provider_key: str
    versions: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "versions", MappingProxyType(dict(self.versions)))


class CapabilityRegistry:
    """Deterministic registry for provider capability discovery and negotiation."""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, CapabilityDescriptor]] = {}

    def register(
        self, provider_key: str, capabilities: tuple[CapabilityDescriptor, ...]
    ) -> None:
        if not provider_key or not capabilities:
            raise ValueError("Provider key and capabilities are required.")
        indexed = {capability.key: capability for capability in capabilities}
        if len(indexed) != len(capabilities):
            raise ValueError("A provider cannot register a capability twice.")
        existing = self._providers.get(provider_key)
        if existing is not None and existing != indexed:
            raise ValueError("Provider capability registration is immutable.")
        self._providers[provider_key] = indexed

    def discover(self, provider_key: str, capability_key: str) -> CapabilityDescriptor:
        try:
            return self._providers[provider_key][capability_key]
        except KeyError as error:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.UNSUPPORTED_CAPABILITY,
                "The requested capability is not supported.",
            ) from error

    def negotiate(
        self, provider_key: str, requested: Mapping[str, tuple[int, ...]]
    ) -> NegotiatedCapabilities:
        versions: dict[str, int] = {}
        for capability_key in sorted(requested):
            descriptor = self.discover(provider_key, capability_key)
            accepted = requested[capability_key]
            if descriptor.version not in accepted:
                raise ProviderCapabilityError(
                    CanonicalErrorCategory.UNSUPPORTED_CAPABILITY,
                    "No compatible capability version is available.",
                )
            versions[capability_key] = descriptor.version
        return NegotiatedCapabilities(provider_key, versions)


def _wire_value(value: Any) -> Any:
    if isinstance(value, ProviderCapabilityError):
        return {
            "category": value.category.value,
            "message": value.safe_message,
            "retry": value.retry.value,
            "retry_after_seconds": value.retry_after_seconds,
        }
    if isinstance(value, ExtensionEnvelope):
        return _wire_value(value.values)
    if is_dataclass(value):
        return {field.name: _wire_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_wire_value(item) for item in value]
    return value


def to_wire(value: Any) -> Any:
    """Convert a canonical contract to provider-neutral JSON-compatible data."""

    return _wire_value(value)


def _from_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if value is None:
        return None
    if origin in (Union, types.UnionType):
        concrete = next(item for item in args if item is not type(None))
        return _from_value(concrete, value)
    if origin is tuple:
        item_type = args[0] if args else Any
        return tuple(_from_value(item_type, item) for item in value)
    if annotation is datetime:
        return datetime.fromisoformat(value)
    if annotation is date:
        return date.fromisoformat(value)
    if annotation is ExtensionEnvelope:
        return ExtensionEnvelope(value)
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return annotation(value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return from_wire(annotation, value)
    return value


def from_wire[T](contract_type: type[T], payload: Mapping[str, Any]) -> T:
    """Rehydrate a canonical dataclass from its versioned wire representation."""

    hints = get_type_hints(contract_type)
    values = {
        field.name: _from_value(hints[field.name], payload[field.name])
        for field in fields(contract_type)
        if field.name in payload
    }
    return contract_type(**values)
