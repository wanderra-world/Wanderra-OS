"""Document custody and negative-path matrix for the H0-07 prototype."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.architecture.custody_prototype import (
    CustodyError,
    CustodyState,
    DocumentCustody,
    InMemoryObjectStorage,
    ScanResult,
    StorageConfiguration,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
CONTENT = b"Atlas custody prototype document"
CONTENT_HASH = hashlib.sha256(CONTENT).hexdigest()
MIME = "application/pdf"


def secure_configuration() -> StorageConfiguration:
    return StorageConfiguration(
        tls_enabled=True,
        managed_encryption=True,
        public_access=False,
        region="eu-north-1",
        backup_enabled=True,
    )


@pytest.fixture
def storage() -> InMemoryObjectStorage:
    return InMemoryObjectStorage(secure_configuration())


@pytest.fixture
def custody(storage: InMemoryObjectStorage) -> DocumentCustody:
    return DocumentCustody(workspace_id=uuid4(), storage=storage)


def quarantine(custody: DocumentCustody):
    return custody.quarantine(
        CONTENT,
        declared_mime=MIME,
        expected_hash=CONTENT_HASH,
        now=NOW,
    )


def promote(custody: DocumentCustody):
    version = quarantine(custody)
    return custody.promote(
        version.id,
        detected_mime=MIME,
        scan_result=ScanResult.CLEAN,
        now=NOW + timedelta(minutes=1),
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"tls_enabled": False}, "requires TLS"),
        ({"managed_encryption": False}, "managed encryption"),
        ({"public_access": True}, "public object storage"),
        ({"region": ""}, "region"),
        ({"backup_enabled": False}, "backup policy"),
    ],
)
def test_fit_custody_001_storage_security_configuration_is_mandatory(
    change: dict[str, object],
    message: str,
) -> None:
    """FIT-CUSTODY-001 rejects unsafe object-storage environments."""

    with pytest.raises(CustodyError, match=message):
        InMemoryObjectStorage(replace(secure_configuration(), **change))


def test_fit_custody_002_content_is_immutable_and_content_addressed(
    custody: DocumentCustody,
    storage: InMemoryObjectStorage,
) -> None:
    """FIT-CUSTODY-002 stores immutable content under an opaque tenant partition."""

    version = quarantine(custody)

    assert version.content_hash in version.object_key
    assert str(version.workspace_id) not in version.object_key
    assert storage.get(version.object_key) == CONTENT
    with pytest.raises(CustodyError, match="cannot be overwritten"):
        storage.put_immutable(version.object_key, b"different content")


def test_fit_custody_003_hash_and_mime_validation_precede_storage(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-003 rejects invalid upload claims before custody acceptance."""

    with pytest.raises(CustodyError, match="hash does not match"):
        custody.quarantine(
            CONTENT,
            declared_mime=MIME,
            expected_hash="0" * 64,
            now=NOW,
        )
    with pytest.raises(CustodyError, match="MIME type is not allowed"):
        custody.quarantine(
            CONTENT,
            declared_mime="application/x-executable",
            expected_hash=CONTENT_HASH,
            now=NOW,
        )


def test_fit_custody_004_quarantine_is_not_readable(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-004 prevents access before complete promotion."""

    version = quarantine(custody)

    with pytest.raises(CustodyError, match="not readable"):
        custody.read(version.id, authorized=True)


@pytest.mark.parametrize("scan_result", [ScanResult.INFECTED, ScanResult.FAILED])
def test_fit_custody_005_scan_failure_prevents_promotion(
    custody: DocumentCustody,
    scan_result: ScanResult,
) -> None:
    """FIT-CUSTODY-005 rejects infected content and scanner failures."""

    version = quarantine(custody)

    with pytest.raises(CustodyError, match="malware scanning"):
        custody.promote(
            version.id,
            detected_mime=MIME,
            scan_result=scan_result,
            now=NOW + timedelta(minutes=1),
        )
    assert custody.current(version.id).state is CustodyState.REJECTED


def test_fit_custody_006_detected_mime_must_match_declaration(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-006 rejects type-confused content."""

    version = quarantine(custody)

    with pytest.raises(CustodyError, match="does not match"):
        custody.promote(
            version.id,
            detected_mime="text/plain",
            scan_result=ScanResult.CLEAN,
            now=NOW + timedelta(minutes=1),
        )
    assert custody.current(version.id).state is CustodyState.QUARANTINED


def test_fit_custody_007_metadata_promotion_is_atomic(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-007 leaves content quarantined when metadata commit fails."""

    version = quarantine(custody)

    with pytest.raises(CustodyError, match="transaction failed"):
        custody.promote(
            version.id,
            detected_mime=MIME,
            scan_result=ScanResult.CLEAN,
            now=NOW + timedelta(minutes=1),
            metadata_commit_succeeds=False,
        )
    assert custody.current(version.id).state is CustodyState.QUARANTINED


def test_fit_custody_008_authorized_promotion_enables_read(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-008 allows content only after successful atomic promotion."""

    version = promote(custody)

    assert version.state is CustodyState.READABLE
    assert custody.read(version.id, authorized=True) == CONTENT
    with pytest.raises(CustodyError, match="not authorized"):
        custody.read(version.id, authorized=False)


def test_fit_custody_009_signed_access_is_authorized_and_short_lived(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-009 prohibits public and permanent object access."""

    version = promote(custody)
    access = custody.issue_signed_access(
        version.id,
        authorized=True,
        now=NOW,
        ttl=timedelta(minutes=5),
    )

    assert access.url.startswith("https://")
    assert access.expires_at == NOW + timedelta(minutes=5)
    with pytest.raises(CustodyError, match="not authorized"):
        custody.issue_signed_access(
            version.id,
            authorized=False,
            now=NOW,
            ttl=timedelta(minutes=1),
        )
    with pytest.raises(CustodyError, match="short-lived"):
        custody.issue_signed_access(
            version.id,
            authorized=True,
            now=NOW,
            ttl=timedelta(minutes=6),
        )


def test_fit_custody_010_legal_hold_and_retention_block_deletion(
    custody: DocumentCustody,
) -> None:
    """FIT-CUSTODY-010 applies governance before destructive deletion."""

    version = promote(custody)
    custody.set_governance(version.id, legal_hold=True, retain_until=None)
    with pytest.raises(CustodyError, match="legal hold"):
        custody.delete(version.id, now=NOW + timedelta(days=1))

    custody.set_governance(
        version.id,
        legal_hold=False,
        retain_until=NOW + timedelta(days=2),
    )
    with pytest.raises(CustodyError, match="retention policy"):
        custody.delete(version.id, now=NOW + timedelta(days=1))


def test_fit_custody_011_eligible_deletion_removes_content(
    custody: DocumentCustody,
    storage: InMemoryObjectStorage,
) -> None:
    """FIT-CUSTODY-011 removes eligible content and records deletion state."""

    version = promote(custody)
    deleted = custody.delete(version.id, now=NOW + timedelta(days=1))

    assert deleted.state is CustodyState.DELETED
    assert not storage.contains(version.object_key)
    with pytest.raises(CustodyError, match="not readable"):
        custody.read(version.id, authorized=True)


def test_fit_custody_012_shared_content_remains_until_last_reference_is_deleted(
    custody: DocumentCustody,
    storage: InMemoryObjectStorage,
) -> None:
    """FIT-CUSTODY-012 avoids deleting a content-addressed object still in use."""

    first = quarantine(custody)
    second = quarantine(custody)
    assert first.object_key == second.object_key

    custody.delete(first.id, now=NOW + timedelta(days=1))
    assert storage.contains(first.object_key)

    custody.delete(second.id, now=NOW + timedelta(days=1))
    assert not storage.contains(first.object_key)


def test_fit_custody_013_abandoned_quarantine_expires(
    custody: DocumentCustody,
    storage: InMemoryObjectStorage,
) -> None:
    """FIT-CUSTODY-013 expires abandoned quarantine objects by lifecycle policy."""

    version = quarantine(custody)
    expired = custody.expire_quarantine(
        now=NOW + timedelta(hours=24),
        maximum_age=timedelta(hours=24),
    )

    assert expired == (version.id,)
    assert custody.current(version.id).state is CustodyState.DELETED
    assert not storage.contains(version.object_key)
