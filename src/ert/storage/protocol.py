from __future__ import annotations
from datetime import datetime
from functools import cached_property, lru_cache
from types import TracebackType
from typing import Iterable, Protocol, TYPE_CHECKING
from uuid import UUID
from abc import ABC, abstractmethod

from ert.storage.mode import BaseMode
from ert.storage.realization_storage_state import RealizationStorageState

if TYPE_CHECKING:
    import xarray as xr
    import numpy as np
    import numpy.typing as npt
    from ert.config import ParameterConfig, ResponseConfig
    from ert.run_models.run_arguments import RunArgumentsType


class Ensemble(ABC, BaseMode):
    """A representation of an ensemble storage

    This class can only be instantiated by having a Storage
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of the ensemble"""

    @property
    @abstractmethod
    def id(self) -> UUID:
        """Get the UUID of the ensemble"""

    @property
    @abstractmethod
    def experiment_id(self) -> UUID:
        """Get the experiment UUID that this ensemble belongs to"""

    @property
    @abstractmethod
    def experiment(self) -> Experiment:
        """Get the experiment that this ensemble belongs to"""

    @property
    @abstractmethod
    def ensemble_size(self) -> int:
        """Get the ensemble size (number of realisations) for this ensemble"""

    @property
    @abstractmethod
    def started_at(self) -> datetime:
        """Get the time when this ensemble was created"""

    @property
    @abstractmethod
    def iteration(self) -> int:
        """Get the iteration that this ensemble represents, when eg. running an ES-MDA"""

    @abstractmethod
    def get_ensemble_state(self) -> list[RealizationStorageState]:
        pass

    @abstractmethod
    def get_realization_mask_with_parameters(self) -> npt.NDArray[np.bool_]:
        pass

    @abstractmethod
    def get_realization_list_with_responses(self, key: str | None = None) -> list[int]:
        pass

    @abstractmethod
    def get_realization_mask_with_responses(self, key: str | None = None) -> npt.NDArray[np.bool_]:
        pass

    @abstractmethod
    def get_realization_mask_without_failure(self) -> npt.NDArray[np.bool_]:
        pass

    @abstractmethod
    def save_parameters(self, group: str, realization: int, dataset: xr.Dataset) -> None:
        pass

    @abstractmethod
    def load_parameters(self, group: str, realizations: int | npt.NDArray[np.int_] | None = None) -> xr.Dataset:
        pass

    @abstractmethod
    def save_response(self, group: str, data: xr.Dataset, realization: int) -> None:
        pass

    @lru_cache
    @abstractmethod
    def load_responses(self, key: str, realizations: tuple[int, ...]) -> xr.Dataset:
        pass

    @abstractmethod
    def set_failure(
        self,
        realization: int,
        failure_type: RealizationStorageState,
        message: str | None = None,
    ) -> None:
        pass

    @abstractmethod
    def get_summary_keyset(self) -> list[str]:
        pass

    @abstractmethod
    def calculate_std_dev_for_parameter(self, parameter_group: str) -> xr.Dataset:
        pass


class Experiment(ABC, BaseMode):
    """A representation of an experiment

    Manages the experiment's parameters, responses, observations, and simulation
    arguments. Provides methods to create and access associated ensembles.

    This is a just a protocol, and not instantiable by itself. Use
    [`Storage.get_experiment`][ert.storage.Storage.get_experiment] or
    [`Storage.create_experiment`][ert.storage.Storage.create_experiment] to
    obtain an object that implements this.

    Currently, only the private class
    [`LocalExperiment`][ert.storage.local_experiment.LocalExperiment] implements
    this for working with local file storage.

    """

    @property
    @abstractmethod
    def id(self) -> UUID:
        """Get the UUID of the experiment"""

    @property
    @abstractmethod
    def ensembles(self) -> Iterable[Ensemble]:
        """Iterator for ensembles that belong this experiment"""

    @abstractmethod
    def create_ensemble(
        self,
        *,
        ensemble_size: int,
        name: str,
        iteration: int = 0,
        prior_ensemble: Ensemble | None = None,
    ) -> Ensemble:
        """Create an [ensemble][ert.storage.Ensemble] that has belongs to this experiment"""

    @property
    @abstractmethod
    def update_parameters(self) -> list[str]:
        """Parameters that will be updated by a"""

    @property
    @abstractmethod
    def observations(self) -> dict[str, xr.Dataset]:
        """Observation data"""

    @property
    @abstractmethod
    def parameter_configuration(self) -> dict[str, ParameterConfig]:
        pass

    @property
    @abstractmethod
    def response_configuration(self) -> dict[str, ResponseConfig]:
        pass

    @abstractmethod
    def refresh(self) -> None:
        """Manually refresh the cached data for this experiment.

        This method is used to refresh the state of the experiment to reflect any
        changes made since the experiment was last accessed.

        """



class Storage(ABC, BaseMode):
    """A representation of the storage for Ert experiments and ensembles.

    This is a just a protocol, and not instantiable by itself. Use
    [`open_storage`][ert.storage.open_storage] to obtain an object that
    implements this.

    Currently, only the private class
    [`LocalStorage`][ert.storage.local_storage.LocalStorage] implements this for
    working with local file storage.

    """

    @abstractmethod
    def refresh(self) -> None:
        """Manually refresh the index, experiments, and ensembles from the storage.

        This method is used to refresh the state of the storage to reflect any
        changes made since the storage was last accessed.

        """

    @abstractmethod
    def get_experiment(self, uuid: UUID) -> Experiment:
        """Retrieves an experiment by UUID.

        Args:
            uuid: The UUID of the experiment to retrieve.

        Returns:
            The experiment associated with the given UUID.

        """

    @abstractmethod
    def get_ensemble(self, uuid: UUID) -> Ensemble:
        """Retrieves an ensemble by UUID.

        Args:
            uuid: The UUID of the ensemble to retrieve.

        Returns:
            The ensemble associated with the given UUID.

        """

    @abstractmethod
    def get_ensemble_by_name(self, name: str) -> Ensemble:
        """Retrieves an ensemble by name.

        Args:
            name: The name of the ensemble to retrieve.

        Returns:
            The ensemble associated with the given name.

        """

    @abstractmethod
    def close(self) -> None:
        """Closes the storage, releasing any acquired locks and saving the index.

        This method should be called to cleanly close the storage, especially
        when it was opened in write mode. Failing to call this method may leave
        a lock file behind, which would interfere with subsequent access to
        the storage.
        """

    @abstractmethod
    def create_experiment(
        self,
        parameters: Iterable[ParameterConfig] = (),
        responses: Iterable[ResponseConfig] = (),
        observations: dict[str, xr.Dataset] | None = None,
        simulation_arguments: RunArgumentsType | None = None,
        name: str | None = None,
    ) -> Experiment:
        """Creates a new experiment in the storage.

        Args:
            parameters: The parameters for the experiment.
            responses: The responses for the experiment.
            observations: The observations for the experiment.
            simulation_arguments: The simulation arguments for the experiment.
            name: The name of the experiment.

        Returns:
            The newly created experiment.

        """

    @abstractmethod
    def create_ensemble(
        self,
        experiment: Experiment | UUID,
        *,
        ensemble_size: int,
        iteration: int = 0,
        name: str | None = None,
        prior_ensemble: Ensemble | UUID | None = None,
    ) -> Ensemble:
        """Creates a new ensemble in the storage.

        Args:
            experiment: The experiment for which the ensemble is created.
            ensemble_size: The number of realizations in the ensemble.
            iteration: The iteration index for the ensemble.
            name: The name of the ensemble.
            prior_ensemble: An optional ensemble to use as a prior.

        Returns:
            The newly created ensemble.

        Raises:
            ValueError: The ensemble size is larger than the prior
                ensemble.
            ert.storage.mode.ModeError: Storage is not open for writing
        """

    @property
    @abstractmethod
    def experiments(self) -> Iterable[Experiment]:
        pass

    @property
    @abstractmethod
    def ensembles(self) -> Iterable[Ensemble]:
        pass

    @abstractmethod
    def __enter__(self) -> Storage:
        """Contextmanager that automatically closes itself"""

    @abstractmethod
    def __exit__(self, exception: Exception, exception_type: type[Exception], traceback: TracebackType) -> None:
        pass
