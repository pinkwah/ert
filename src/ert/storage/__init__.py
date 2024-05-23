"""
# Ert Storage

The results of an Ert experiment evaluation is stored in Ert storage.
"""
from __future__ import annotations

import os
from pathlib import Path

from ert.storage.local_storage import LocalStorage
from ert.storage.mode import Mode, ModeLiteral, ModeError
from ert.storage.protocol import Storage, Experiment, Ensemble

# Kept here to avoid having to have to rewrite a lot of files
StorageReader = Storage
StorageAccessor = Storage
ExperimentReader = Experiment
ExperimentAccessor = Experiment
EnsembleReader = Ensemble
EnsembleAccessor = Ensemble


def open_storage(
    path: str | os.PathLike[str], mode: ModeLiteral | Mode = "r"
) -> Storage:
    """Open storage for reading or writing

    Args:
        path: Path where the storage is located
        mode ("r" | "w"): Open in read-only ("r") or read-write ("w") mode

    Returns:
        Returns an instance of `Storage`
    """

    return LocalStorage(Path(path), Mode(mode))


__all__ = [
    "Ensemble",
    "Experiment",
    "Storage",
    "Mode",
    "ModeError",
    "ModeLiteral",
    "open_storage",
]
