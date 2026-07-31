"""Managed connection credential loading for authorized capability factories."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.repository import ConnectionCredentialRepository
from app.encryption.repository import EncryptionRepository
from app.encryption.service import EnvelopeEncryptionService
from app.execution_context import ExecutionContext
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    ProviderCapabilityError,
)


class ManagedConnectionCredentialLoader:
    """Workspace-bound credential lookup and envelope decryption."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        connection_id: uuid.UUID,
        encryption: EnvelopeEncryptionService,
        credential_kind: str = "oauth_refresh_token",
    ) -> None:
        self._context = context
        self._connection_id = connection_id
        self._credential_kind = credential_kind
        self._credentials = ConnectionCredentialRepository(session, context)
        self._envelopes = EncryptionRepository(session, context)
        self._encryption = encryption

    async def load(self) -> bytes:
        credential = await self._credentials.latest_generation(
            self._connection_id, self._credential_kind
        )
        if credential is None or credential.status not in {
            "active",
            "shadow_verified",
        }:
            raise self._unavailable()
        envelope = await self._envelopes.get(
            workspace_id=self._context.tenant.workspace_id,
            envelope_id=credential.envelope_id,
        )
        if envelope is None:
            raise self._unavailable()
        return await self._encryption.decrypt(envelope)

    @staticmethod
    def _unavailable() -> ProviderCapabilityError:
        return ProviderCapabilityError(
            CanonicalErrorCategory.AUTHENTICATION,
            "The managed capability credential is unavailable.",
        )
