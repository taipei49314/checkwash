"""FileChange and EngineError — shared so roles/ci do not import engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileChange:
    path: str  # forward-slash normalized
    status: str  # added | modified | deleted
    before: bytes | None
    after: bytes | None
    old_path: str | None = None  # set for git renames (R status)
    synthetic: str | None = None  # marks halves of an expanded rename


class EngineError(Exception):
    # Only stand-in step-limit failures attach this finite source diagnostic.
    # Keep the legacy exception string and all other error handling unchanged.
    standin_step_diagnostic: str | None = None
