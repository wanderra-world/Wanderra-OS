"""Provider-neutral integration errors exposed to application boundaries."""

from __future__ import annotations


class ProviderOperationError(RuntimeError):
    """A sanitized external-provider failure suitable for API translation."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
