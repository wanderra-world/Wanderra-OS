"""Migration-only adapter for accepted Phase 1 credential shadow columns."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import CalendarCredential
from app.models.drive import DriveCredential
from app.models.gmail import GmailCredential

_SOURCES = {
    "gmail_credentials": GmailCredential,
    "calendar_credentials": CalendarCredential,
    "drive_credentials": DriveCredential,
}


class PhaseOneShadowLinker:
    """Write only H1 shadow evidence; never changes authoritative ciphertext."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def link_verified_shadow(
        self,
        *,
        source_system: str,
        source_record_id: str,
        workspace_id: uuid.UUID,
        envelope_id: uuid.UUID,
        checksum: str,
        verified_at: datetime,
    ) -> None:
        model = _SOURCES.get(source_system)
        if model is None:
            raise ValueError("legacy credential source is unsupported")
        try:
            user_id = uuid.UUID(source_record_id)
        except ValueError as error:
            raise ValueError("legacy credential record id is invalid") from error
        record = await self._session.get(model, user_id, with_for_update=True)
        if record is None or record.workspace_id != workspace_id:
            raise ValueError("legacy credential source is unavailable")
        if record.envelope_id is not None and record.envelope_id != envelope_id:
            raise ValueError("legacy credential already has a different shadow")
        record.envelope_id = envelope_id
        record.envelope_legacy_checksum = checksum
        record.envelope_verified_at = verified_at
        record.envelope_cutover = False
