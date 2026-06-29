"""CheckpointTime — a reversible, deduplicated checkpoint store for long-running jobs.

Snapshots of slowly-changing state are content-addressed and chunk-deduplicated,
so N near-identical checkpoints cost roughly one full copy plus deltas. You can
rewind HEAD to any earlier checkpoint or branch a new named timeline.
"""
from __future__ import annotations

from .store import CheckpointStore, CheckpointError

__all__ = ["CheckpointStore", "CheckpointError"]
__version__ = "0.1.0"
