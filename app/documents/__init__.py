"""H3-03 provider-neutral document custody and governed derivation."""

from app.documents.contracts import (
    Classification,
    CustodyError,
    DeletionDisposition,
    DocumentCreate,
    DocumentVersionCreate,
    ExtractionRequest,
    MalwareVerdict,
    VerificationEvidence,
)
from app.documents.service import DocumentService

__all__ = [
    "Classification",
    "CustodyError",
    "DeletionDisposition",
    "DocumentCreate",
    "DocumentService",
    "DocumentVersionCreate",
    "ExtractionRequest",
    "MalwareVerdict",
    "VerificationEvidence",
]
