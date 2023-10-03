from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from multiprocessing.pool import ThreadPool
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence, Tuple, Union, Set
from uuid import UUID

import numpy as np
import xarray as xr
from pydantic import BaseModel, Field

from ert.callbacks import forward_model_ok
from ert.load_status import LoadResult, LoadStatus

if TYPE_CHECKING:
    import numpy.typing as npt

    from ert.run_arg import RunArg
    from ert.storage.local_experiment import (
        LocalExperimentAccessor,
        LocalExperimentReader,
    )
    from ert.storage.local_storage import LocalStorageAccessor, LocalStorageReader

logger = logging.getLogger(__name__)


def _load_realization(
    sim_fs: LocalEnsembleAccessor,
    realisation: int,
    run_args: List[RunArg],
) -> Tuple[LoadResult, int]:
    result = forward_model_ok(run_args[realisation])
    return result, realisation


class _Index(BaseModel):
    id: UUID
    experiment_id: UUID
    ensemble_size: int
    iteration: int
    name: str
    prior_ensemble_id: Optional[UUID]
    started_at: datetime
    failures: Set[int] = Field(default_factory=set)


# pylint: disable=R0904
class LocalEnsembleReader:
    def __init__(
        self,
        storage: LocalStorageReader,
        path: Path,
    ):
        self._storage: Union[LocalStorageReader, LocalStorageAccessor] = storage
        self._path = path
        self._index = _Index.parse_file(path / "index.json")
        self._experiment_path = self._path / "experiment"

        self._initialized: Set[int] = set()
        self._complete_realizations: Set[int] = set()
        self._check_complete_realizations()
        self._check_parameters_initialized()

    @property
    def mount_point(self) -> Path:
        return self._path

    @property
    def name(self) -> str:
        return self._index.name

    @property
    def id(self) -> UUID:
        return self._index.id

    @property
    def experiment_id(self) -> UUID:
        return self._index.experiment_id

    @property
    def ensemble_size(self) -> int:
        return self._index.ensemble_size

    @property
    def started_at(self) -> datetime:
        return self._index.started_at

    @property
    def iteration(self) -> int:
        return self._index.iteration

    @property
    def failures(self) -> Iterable[int]:
        return self._index.failures

    @property
    def experiment(self) -> Union[LocalExperimentReader, LocalExperimentAccessor]:
        return self._storage.get_experiment(self.experiment_id)

    @property
    def initialized(self) -> Set[int]:
        return self._initialized

    @property
    def uninitialized(self) -> Set[int]:
        return set(range(self.ensemble_size)) - self.initialized

    @property
    def complete_realizations(self) -> Set[int]:
        return self._complete_realizations

    def close(self) -> None:
        self.sync()

    def sync(self) -> None:
        pass

    def get_summary_keyset(self) -> List[str]:
        realization_folders = list(self.mount_point.glob("realization-*"))
        if not realization_folders:
            return []
        summary_path = realization_folders[0] / "summary.nc"
        if not summary_path.exists():
            return []
        realization_nr = int(str(realization_folders[0])[-1])
        response = self.load_response("summary", (realization_nr,))
        keys = sorted(response["name"].values)
        return keys

    def _check_complete_realizations(
        self, realizations: Optional[Iterable[int]] = None
    ) -> None:
        if realizations is None:
            realizations = range(self.ensemble_size)

        files = {
            f"{resp.name}.nc"
            for resp in self.experiment.response_configuration.values()
        }
        for iens in realizations:
            if iens in self._complete_realizations:
                continue

            path = self._path / f"realization-{iens}"
            if all(map(lambda f: (path / f).exists(), files)):
                self._complete_realizations.add(iens)

    def _check_parameters_initialized(
        self, realizations: Optional[Sequence[int]] = None
    ) -> None:
        if realizations is None:
            realizations = range(self.ensemble_size)

        files = {
            f"{param.name}.nc"
            for param in self.experiment.parameter_configuration.values()
            if not param.forward_init
        }
        for iens in realizations:
            if iens in self._initialized:
                continue

            path = self._path / f"realization-{iens}"
            if all(map(lambda f: (path / f).exists(), files)):
                self._initialized.add(iens)

    def _load_single_dataset(
        self,
        group: str,
        realization: int,
    ) -> xr.Dataset:
        try:
            return xr.open_dataset(
                self.mount_point / f"realization-{realization}" / f"{group}.nc",
                engine="scipy",
            )
        except FileNotFoundError as e:
            raise KeyError(
                f"No dataset '{group}' in storage for realization {realization}"
            ) from e

    def _load_dataset(
        self,
        group: str,
        realizations: Union[int, npt.NDArray[np.int_], None],
    ) -> xr.Dataset:
        if isinstance(realizations, int):
            return self._load_single_dataset(group, realizations).isel(
                realizations=0, drop=True
            )

        if realizations is None:
            datasets = [
                xr.open_dataset(p, engine="scipy")
                for p in sorted(self.mount_point.glob(f"realization-*/{group}.nc"))
            ]
        else:
            datasets = [self._load_single_dataset(group, i) for i in realizations]
        return xr.combine_nested(datasets, "realizations")

    def load_parameters(
        self,
        group: str,
        realizations: Union[int, npt.NDArray[np.int_], None] = None,
        *,
        var: str = "values",
    ) -> xr.DataArray:
        return self._load_dataset(group, realizations)[var]

    @lru_cache  # noqa: B019
    def load_response(self, key: str, realizations: Tuple[int, ...]) -> xr.Dataset:
        loaded = []
        for realization in realizations:
            input_path = self.mount_point / f"realization-{realization}" / f"{key}.nc"
            if not input_path.exists():
                raise KeyError(f"No response for key {key}, realization: {realization}")
            ds = xr.open_dataset(input_path, engine="scipy")
            loaded.append(ds)
        response = xr.combine_nested(loaded, concat_dim="realization")
        assert isinstance(response, xr.Dataset)
        return response


class LocalEnsembleAccessor(LocalEnsembleReader):
    def __init__(
        self,
        storage: LocalStorageAccessor,
        path: Path,
    ) -> None:
        super().__init__(storage, path)
        self._storage: LocalStorageAccessor = storage

    @classmethod
    def create(
        cls,
        storage: LocalStorageAccessor,
        path: Path,
        uuid: UUID,
        *,
        ensemble_size: int,
        experiment_id: UUID,
        iteration: int = 0,
        name: str,
        prior_ensemble_id: Optional[UUID],
    ) -> LocalEnsembleAccessor:
        (path / "experiment").mkdir(parents=True, exist_ok=False)

        index = _Index(
            id=uuid,
            ensemble_size=ensemble_size,
            experiment_id=experiment_id,
            iteration=iteration,
            name=name,
            prior_ensemble_id=prior_ensemble_id,
            started_at=datetime.now(),
        )

        with open(path / "index.json", mode="w", encoding="utf-8") as f:
            print(index.json(), file=f)

        return cls(storage, path)

    def sync(self) -> None:
        pass

    def load_from_run_path(
        self,
        ensemble_size: int,
        run_args: List[RunArg],
        active_realizations: List[bool],
    ) -> int:
        """Returns the number of loaded realizations"""
        pool = ThreadPool(processes=8)

        async_result = [
            pool.apply_async(
                _load_realization,
                (self, iens, run_args),
            )
            for iens in range(ensemble_size)
            if active_realizations[iens]
        ]

        loaded = 0
        for t in async_result:
            ((status, message), iens) = t.get()

            if status == LoadStatus.LOAD_SUCCESSFUL:
                loaded += 1
            else:
                print(f"Realization: {iens}, load failure: {message}")

        return loaded

    def save_parameters(
        self, group: str, realization: int, dataset: xr.Dataset
    ) -> None:
        """Saves the provided dataset under a parameter group and realization index

        Args:
            group: Name of the parameter group under which the dataset is to be saved

            realization: Which realization index this group belongs to

            dataset: Dataset to save. It must contain a variable named
                    'values' which will be used when flattening out the
                    parameters into a 1d-vector.
        """
        if "values" not in dataset.variables:
            raise ValueError(
                f"Dataset for parameter group '{group}' "
                f"must contain a 'values' variable"
            )

        path = self.mount_point / f"realization-{realization}" / f"{group}.nc"
        path.parent.mkdir(exist_ok=True)
        dataset.expand_dims(realizations=[realization]).to_netcdf(path, engine="scipy")

    def save_response(self, group: str, data: xr.Dataset, realization: int) -> None:
        data = data.expand_dims({"realization": [realization]})
        output_path = self.mount_point / f"realization-{realization}"
        Path.mkdir(output_path, parents=True, exist_ok=True)

        data.to_netcdf(output_path / f"{group}.nc", engine="scipy")

    def set_failures(self, failures: Set[int]) -> None:
        self._index.failures |= failures
        self.sync()
