"""KnotVault — a tamper-evident file/folder archiver.

Think "zip + a cryptographic integrity receipt". Files are content-addressed,
exact-duplicate chunks collapse automatically, and every archive carries a
Merkle root you can later use to PROVE nothing changed — or to pinpoint exactly
which file was tampered with.

Public surface:
    Vault             -- core archiver (wraps the KNOTstore engine)
    ArchiveEntry      -- one file inside an archive
    VaultError        -- base error for all expected failures
    TamperError       -- raised when verification detects corruption/tampering
"""
from __future__ import annotations

from .vault import (
    Vault,
    ArchiveEntry,
    VaultError,
    TamperError,
)

__all__ = ["Vault", "ArchiveEntry", "VaultError", "TamperError"]
__version__ = "0.1.0"
