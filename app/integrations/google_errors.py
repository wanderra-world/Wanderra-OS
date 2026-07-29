"""Google adapter error translation.

Google SDK exceptions must not escape the integration boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from googleapiclient.errors import HttpError

from app.integrations.errors import ProviderOperationError


async def execute_google_request[ResultT](operation: Callable[[], ResultT]) -> ResultT:
    """Execute blocking Google work and translate SDK-specific HTTP errors."""

    try:
        return await asyncio.to_thread(operation)
    except HttpError as error:
        status_code = int(getattr(error.resp, "status", 502))
        message = error.reason or "The external provider request failed."
        raise ProviderOperationError(status_code, message) from error
