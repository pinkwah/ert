Ert Storage client
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

```py
from ert.storage import open_storage

with open_storage("storage") as storage:
    for exp in storage.experiments:
        print(f"{exp.id}: {exp.name}")
        for ens in exp.ensembles:
            print(f"    {ens.id}: {ens.name}")
```

Example output may be:
```sh
esmda
    default_3
    default_2
    default_1
    default_0
experiment
    default
```
