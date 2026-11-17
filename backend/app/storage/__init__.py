"""Private immutable object-storage boundary."""

from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.fake import FakeObjectStorage
from app.storage.files import PreparedContent, VerifiedContent, prepare_content
from app.storage.keys import TrustedKeyBuilder
from app.storage.types import ObjectIdentity, ObjectMetadata, StoragePurpose

__all__ = [
    "FakeObjectStorage",
    "ObjectIdentity",
    "ObjectMetadata",
    "PreparedContent",
    "StorageCoordinator",
    "StorageError",
    "StorageErrorCode",
    "StoragePurpose",
    "TrustedKeyBuilder",
    "VerifiedContent",
    "prepare_content",
]
