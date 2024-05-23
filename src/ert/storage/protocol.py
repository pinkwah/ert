from __future__ import annotations
import datetime
from types import TracebackType
from typing import Iterable, Protocol, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import xarray as xr
    from ert.config import ParameterConfig, ResponseConfig
    from ert.run_models.run_arguments import RunArgumentsType


class Ensemble(Protocol):
    """A representation of an ensemble storage

    This class can only be instantiated by having a Storage
    """

    @property
    def name(self) -> str:
        """Get the name of the ensemble"""

    @property
    def id(self) -> UUID:
        """Get the UUID of the ensemble"""

    @property
    def experiment_id(self) -> UUID:
        """Get the experiment UUID that this ensemble belongs to"""

    @property
    def experiment(self) -> Experiment:
        """Get the experiment that this ensemble belongs to"""

    @property
    def ensemble_size(self) -> int:
        """Get the ensemble size (number of realisations) for this ensemble"""

    @property
    def started_at(self) -> datetime:
        """Get the time when this ensemble was created"""

    @property
    def iteration(self) -> int:
        """Get the iteration that this ensemble represents, when eg. running an ES-MDA"""

    @property
    def parent_id(self) -> UUID | None:
        """Get the UUID of the prior ensemble, if applicable"""


class Experiment(Protocol):
    pass


class Storage(Protocol):
    """A representation of the storage for Ert experiments and ensembles.

    To instantiate this class, use open_storage
    """

    def refresh(self) -> None:
        """Manually refresh the index, experiments, and ensembles from the storage.

        This method is used to refresh the state of the storage to reflect any
        changes made since the storage was last accessed.

        """

    def get_experiment(self, uuid: UUID) -> Experiment:
        """Retrieves an experiment by UUID.

        Args:
            uuid: The UUID of the experiment to retrieve.

        Returns:
            The experiment associated with the given UUID.

        """

    def get_ensemble(self, uuid: UUID) -> Ensemble:
        """Retrieves an ensemble by UUID.

        Args:
            uuid: The UUID of the ensemble to retrieve.

        Returns:
            The ensemble associated with the given UUID.

        """

    def get_ensemble_by_name(self, name: str) -> Ensemble:
        """Retrieves an ensemble by name.

        Args:
            name: The name of the ensemble to retrieve.

        Returns:
            The ensemble associated with the given name.

        """

    def close(self) -> None:
        """Closes the storage, releasing any acquired locks and saving the index.

        This method should be called to cleanly close the storage, especially
        when it was opened in write mode. Failing to call this method may leave
        a lock file behind, which would interfere with subsequent access to
        the storage.
        """

    def create_experiment(
        self,
        parameters: Iterable[ParameterConfig] = (),
        responses: Iterable[ResponseConfig] = (),
        observations: Iterable[tuple[str, xr.Dataset]] = (),
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

    def __enter__(self) -> Storage:
        """Contextmanager that automatically closes itself"""

    def __exit__(self, exception: Exception, exception_type: type[Exception], traceback: TracebackType) -> None:
        pass
