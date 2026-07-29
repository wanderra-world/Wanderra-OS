"""Tests for provider-neutral Google SDK error translation."""

from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError

from app.integrations.errors import ProviderOperationError
from app.integrations.google_errors import execute_google_request


@pytest.mark.asyncio
async def test_google_http_error_is_translated_at_adapter_boundary() -> None:
    response = Mock(status=429, reason="Too Many Requests")
    provider_error = HttpError(
        response,
        b'{"error": {"message": "Provider quota exceeded"}}',
    )

    def fail() -> None:
        raise provider_error

    with pytest.raises(ProviderOperationError) as captured:
        await execute_google_request(fail)

    assert captured.value.status_code == 429
    assert str(captured.value) == "Provider quota exceeded"
    assert captured.value.__cause__ is provider_error
