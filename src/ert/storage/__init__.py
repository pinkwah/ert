"""Ert Storage client
==================

Ert stores the data that is produced during an ensemble evaluation in something
we call "Ert Storage". By default, all data is stored locally on disk. The
location of the data is given by the Ert config keyword `ENSPATH` which is
`storage/` by default. The contents of this is various metadata of previous
evaluations, like the entire configuration, which parameters existed and their
values, and the response data.

Interaction with the storage starts with the
[`open_storage`][ert.storage.open_storage] function. It is designed to be
reminiscent of the `open` function that one uses for opening files in Python.

The following is a simple example that opens an existing on-disk storage located
in the `storage` directory, and prints the experiments and their ensembles.

```pycon
>>> from ert.storage import open_storage
>>> storage = open_storage("storage")
...    for exp in storage.experiments:
...        print(f"{exp.id}: {exp.name}")
...        for ens in exp.ensembles:
...            print(f"    {ens.id}: {ens.name}")
esmda
    default_3
    default_2
    default_1
    default_0
experiment
    default
```

Structure
---------

A storage contains data related to Ert ensemble evaluations. In the big picture,
a [Storage][ert.storage.Storage] object contains
[Experiments][ert.storage.Experiment], which contain
[Ensembles][ert.storage.Ensemble], which contain realisations.

The Experiment object is meant to contain information relating to the overall
evaluation. It contains the Ert config, as specified by the user, the forward
model, any observations that may be used, and information on how to update
priors, among other things.

The Ensemble object represents an ensemble of realisations and its associated
data, like generated parameters (eg. `GEN_KW`), responses (eg. `GEN_DATA`) and
their numeric values. A standard ensemble evaluation, eg. via "Ensemble
Experiment" option in the GUI will produce one experiment and one ensemble. A
ES-MDA run with four iterations, four ensemble objects will be created, all
belongning to the same experiment. In a multi-ensemble evaluation, the updated
posteriors, calculated from response and obervsation data, in one ensemble
become the priors of the next ensemble.

Numerical Data
--------------

Storage uses a combination of Python and [xarray.Dataset] types. The former for
simple data types and the latter for multi-dimensional array based data, like
parameters, observations and responses. Xarray allows for simple organisation of
multi-dimensional array-based data with labeled axes.

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

    This factory function is the only entry point into the Storage API.

    Args:
        path: Path where the storage is located
        mode ("r" | "w"): Open in read-only ("r") or read-write ("w") mode

    Returns:
        Returns a new instance of `Storage`

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
