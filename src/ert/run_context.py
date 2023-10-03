from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Iterator, List, Sequence

import numpy as np

from .run_arg import RunArg
from .runpaths import Runpaths

if TYPE_CHECKING:
    import numpy.typing as npt

    from .storage import EnsembleAccessor


@dataclass
class RunContext:
    sim_fs: EnsembleAccessor
    runpaths: Runpaths
    initial_mask: Iterable[int] = field(default_factory=set)
    iteration: int = 0

    def __post_init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.run_args = []
        paths = self.runpaths.get_paths(
            range(self.sim_fs.ensemble_size), self.iteration
        )
        job_names = self.runpaths.get_jobnames(
            range(self.sim_fs.ensemble_size), self.iteration
        )

        assert not any(map(lambda x: isinstance(x, bool), self.initial_mask))
        for iens, (run_path, job_name) in enumerate(zip(paths, job_names)):
            self.run_args.append(
                RunArg(
                    str(self.run_id),
                    self.sim_fs,
                    iens,
                    self.iteration,
                    run_path,
                    job_name,
                    iens in self.initial_mask,
                )
            )

    @property
    def mask(self) -> List[bool]:
        return [real.active for real in self]

    @property
    def indices(self) -> Iterable[int]:
        return [i for i, real in enumerate(self) if real.active]

    def is_active(self, index: int) -> bool:
        return self[index].active

    @property
    def active_realizations(self) -> List[int]:
        return [i for i, real in enumerate(self) if real.active]

    def __len__(self) -> int:
        return self.sim_fs.ensemble_size

    def __getitem__(self, item: int) -> "RunArg":
        return self.run_args[item]

    def __iter__(self) -> Iterator["RunArg"]:
        yield from self.run_args

    def deactivate_realization(self, realization_nr: int) -> None:
        self[realization_nr].active = False
