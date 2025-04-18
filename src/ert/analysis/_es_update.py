from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable, Iterable, Sequence
from fnmatch import fnmatch
from typing import (
    TYPE_CHECKING,
    Generic,
    Self,
    TypeVar,
)

import iterative_ensemble_smoother as ies
import numpy as np
import polars as pl
import psutil
import scipy
from iterative_ensemble_smoother.experimental import AdaptiveESMDA

from ert.config import ESSettings, GenKwConfig, ObservationGroups, UpdateSettings

from . import misfit_preprocessor
from .event import (
    AnalysisCompleteEvent,
    AnalysisDataEvent,
    AnalysisErrorEvent,
    AnalysisEvent,
    AnalysisStatusEvent,
    AnalysisTimeEvent,
    DataSection,
)
from .snapshots import (
    ObservationAndResponseSnapshot,
    SmootherSnapshot,
)

if TYPE_CHECKING:
    import numpy.typing as npt

    from ert.storage import Ensemble

logger = logging.getLogger(__name__)


class ErtAnalysisError(Exception):
    pass


def noop_progress_callback(_: AnalysisEvent) -> None:
    pass


T = TypeVar("T")


class TimedIterator(Generic[T]):
    SEND_FREQUENCY = 1.0  # seconds

    def __init__(
        self, iterable: Sequence[T], callback: Callable[[AnalysisEvent], None]
    ) -> None:
        self._start_time = time.perf_counter()
        self._iterable = iterable
        self._callback = callback
        self._index = 0
        self._last_send_time = 0.0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        try:
            result = self._iterable[self._index]
        except IndexError as e:
            raise StopIteration from e

        if self._index != 0:
            elapsed_time = time.perf_counter() - self._start_time
            estimated_remaining_time = (elapsed_time / (self._index)) * (
                len(self._iterable) - self._index
            )
            if elapsed_time - self._last_send_time > self.SEND_FREQUENCY:
                self._callback(
                    AnalysisTimeEvent(
                        remaining_time=estimated_remaining_time,
                        elapsed_time=elapsed_time,
                    )
                )
                self._last_send_time = elapsed_time

        self._index += 1
        return result


def _all_parameters(
    ensemble: Ensemble,
    iens_active_index: npt.NDArray[np.int_],
) -> npt.NDArray[np.float64]:
    """Return all parameters in assimilation problem"""

    param_groups = list(ensemble.experiment.parameter_configuration.keys())

    param_arrays = [
        _load_param_ensemble_array(ensemble, param_group, iens_active_index)
        for param_group in param_groups
    ]

    return np.vstack(param_arrays)


def _save_param_ensemble_array_to_disk(
    ensemble: Ensemble,
    param_ensemble_array: npt.NDArray[np.float64],
    param_group: str,
    iens_active_index: npt.NDArray[np.int_],
) -> None:
    config_node = ensemble.experiment.parameter_configuration[param_group]
    for i, realization in enumerate(iens_active_index):
        config_node.save_parameters(ensemble, realization, param_ensemble_array[:, i])


def _load_param_ensemble_array(
    ensemble: Ensemble,
    param_group: str,
    iens_active_index: npt.NDArray[np.int_],
) -> npt.NDArray[np.float64]:
    config_node = ensemble.experiment.parameter_configuration[param_group]
    return config_node.load_parameters(ensemble, iens_active_index)


def _expand_wildcards(
    input_list: npt.NDArray[np.str_], patterns: list[str]
) -> list[str]:
    """
    Returns a sorted list of unique strings from `input_list` that match any of the specified wildcard patterns.

    Examples:
        >>> _expand_wildcards(np.array(["apple", "apricot", "banana"]), ["apricot", "apricot"])
        ['apricot']
        >>> _expand_wildcards(np.array(["apple", "banana", "apricot"]), [])
        []
        >>> _expand_wildcards(np.array(["dog", "deer", "frog"]), ["d*"])
        ['deer', 'dog']
        >>> _expand_wildcards(np.array(["apple", "APPLE", "Apple"]), ["apple"])
        ['apple']
    """
    matches = []
    for pattern in patterns:
        matches.extend([str(val) for val in input_list if fnmatch(val, pattern)])
    return sorted(set(matches))


def _load_observations_and_responses(
    ensemble: Ensemble,
    alpha: float,
    std_cutoff: float,
    global_std_scaling: float,
    iens_active_index: npt.NDArray[np.int_],
    selected_observations: Iterable[str],
    auto_scale_observations: list[ObservationGroups] | None,
    progress_callback: Callable[[AnalysisEvent], None],
) -> tuple[
    npt.NDArray[np.float64],
    tuple[
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
        list[ObservationAndResponseSnapshot],
    ],
]:
    observations_and_responses = ensemble.get_observations_and_responses(
        selected_observations,
        iens_active_index,
    )

    observations_and_responses = observations_and_responses.sort(
        by=["observation_key", "index"]
    )

    S = observations_and_responses.select(
        observations_and_responses.columns[5:]
    ).to_numpy()
    observations = (
        observations_and_responses.select("observations").to_numpy().reshape((-1,))
    )
    errors = observations_and_responses.select("std").to_numpy().reshape((-1,))
    obs_keys = (
        observations_and_responses.select("observation_key").to_numpy().reshape((-1,))
    )
    indexes = observations_and_responses.select("index").to_numpy().reshape((-1,))

    # Inflating measurement errors by a factor sqrt(global_std_scaling) as shown
    # in for example evensen2018 - Analysis of iterative ensemble smoothers for
    # solving inverse problems.
    # `global_std_scaling` is 1.0 for ES.
    scaling = np.sqrt(global_std_scaling) * np.ones_like(errors)
    scaled_errors = errors * scaling

    # Identifies non-outlier observations based on responses.
    ens_mean = S.mean(axis=1)
    ens_std = S.std(ddof=0, axis=1, dtype=np.float64).astype(np.float32)
    ens_std_mask = ens_std > std_cutoff
    ens_mean_mask = abs(observations - ens_mean) <= alpha * (ens_std + scaled_errors)
    obs_mask = np.logical_and(ens_mean_mask, ens_std_mask)

    if auto_scale_observations:
        scaling_factors_dfs = []

        for input_group in auto_scale_observations:
            group = _expand_wildcards(obs_keys, input_group)
            logger.info(f"Scaling observation group: {group}")
            obs_group_mask = np.isin(obs_keys, group) & obs_mask
            if not any(obs_group_mask):
                logger.error(f"No observations active for group: {input_group}")
                continue
            scaling_factors, clusters, nr_components = misfit_preprocessor.main(
                S[obs_group_mask], scaled_errors[obs_group_mask]
            )
            scaling[obs_group_mask] *= scaling_factors

            scaling_factors_dfs.append(
                pl.DataFrame(
                    {
                        "input_group": [", ".join(input_group)] * len(scaling_factors),
                        "index": indexes[obs_group_mask],
                        "obs_key": obs_keys[obs_group_mask],
                        "scaling_factor": pl.Series(scaling_factors, dtype=pl.Float32),
                    }
                )
            )

            progress_callback(
                AnalysisDataEvent(
                    name="Auto scale: " + ", ".join(input_group),
                    data=DataSection(
                        header=[
                            "Observation",
                            "Index",
                            "Cluster",
                            "Nr components",
                            "Scaling factor",
                        ],
                        data=np.array(
                            (
                                obs_keys[obs_group_mask],
                                indexes[obs_group_mask],
                                clusters,
                                nr_components.astype(int),
                                scaling_factors,
                            )
                        ).T,  # type: ignore
                    ),
                )
            )

        if scaling_factors_dfs:
            scaling_factors_df = pl.concat(scaling_factors_dfs)
            ensemble.save_observation_scaling_factors(scaling_factors_df)

            # Recompute with updated scales
            scaled_errors = errors * scaling
        else:
            msg = (
                f"WARNING: Could not auto-scale the observations {auto_scale_observations}. "
                f"No match with existing active observations {obs_keys}"
            )
            logger.warning(msg)
            print(msg)

    update_snapshot = []
    for (
        obs_name,
        obs_val,
        obs_std,
        obs_scaling,
        response_mean,
        response_std,
        response_mean_mask,
        response_std_mask,
        index,
    ) in zip(
        obs_keys,
        observations,
        errors,
        scaling,
        ens_mean,
        ens_std,
        ens_mean_mask,
        ens_std_mask,
        indexes,
        strict=False,
    ):
        update_snapshot.append(
            ObservationAndResponseSnapshot(
                obs_name=obs_name,
                obs_val=obs_val,
                obs_std=obs_std,
                obs_scaling=obs_scaling,
                response_mean=response_mean,
                response_std=response_std,
                response_mean_mask=bool(response_mean_mask),
                response_std_mask=bool(response_std_mask),
                index=index,
            )
        )

    for missing_obs in obs_keys[~obs_mask]:
        logger.warning(f"Deactivating observation: {missing_obs}")

    return S[obs_mask], (
        observations[obs_mask],
        scaled_errors[obs_mask],
        update_snapshot,
    )


def _split_by_batchsize(
    arr: npt.NDArray[np.int_], batch_size: int
) -> list[npt.NDArray[np.int_]]:
    """
    Splits an array into sub-arrays of a specified batch size.

    Examples
    --------
    >>> num_params = 10
    >>> batch_size = 3
    >>> s = np.arange(0, num_params)
    >>> _split_by_batchsize(s, batch_size)
    [array([0, 1, 2, 3]), array([4, 5, 6]), array([7, 8, 9])]

    >>> num_params = 10
    >>> batch_size = 10
    >>> s = np.arange(0, num_params)
    >>> _split_by_batchsize(s, batch_size)
    [array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])]

    >>> num_params = 10
    >>> batch_size = 20
    >>> s = np.arange(0, num_params)
    >>> _split_by_batchsize(s, batch_size)
    [array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])]
    """
    sections = 1 if batch_size > len(arr) else len(arr) // batch_size
    return np.array_split(arr, sections)


def _calculate_adaptive_batch_size(num_params: int, num_obs: int) -> int:
    """Calculate adaptive batch size to optimize memory usage during Adaptive Localization
    Adaptive Localization calculates the cross-covariance between parameters and responses.
    Cross-covariance is a matrix with shape num_params x num_obs which may be larger than memory.
    Therefore, a batching algorithm is used where only a subset of parameters is used when
    calculating cross-covariance.
    This function calculates a batch size that can fit into the available memory, accounting
    for a safety margin.

    Derivation of formula:
    ---------------------
    available_memory = (amount of available memory on system) * memory_safety_factor
    required_memory = num_params * num_obs * bytes_in_float32
    num_params = required_memory / (num_obs * bytes_in_float32)
    We want (required_memory < available_memory) so:
    num_params < available_memory / (num_obs * bytes_in_float32)

    The available memory is checked using the `psutil` library, which provides information about
    system memory usage.
    From `psutil` documentation:
    - available:
        the memory that can be given instantly to processes without the
        system going into swap.
        This is calculated by summing different memory values depending
        on the platform and it is supposed to be used to monitor actual
        memory usage in a cross platform fashion.
    """
    available_memory_in_bytes = psutil.virtual_memory().available
    memory_safety_factor = 0.8
    # Fields are stored as 32-bit floats.
    bytes_in_float32 = 4
    return min(
        int(
            np.floor(
                (available_memory_in_bytes * memory_safety_factor)
                / (num_obs * bytes_in_float32)
            )
        ),
        num_params,
    )


def _copy_unupdated_parameters(
    all_parameter_groups: Iterable[str],
    updated_parameter_groups: Iterable[str],
    iens_active_index: npt.NDArray[np.int_],
    source_ensemble: Ensemble,
    target_ensemble: Ensemble,
) -> None:
    """
    Copies parameter groups that have not been updated from a source ensemble to a target ensemble.
    This function ensures that all realizations in the target ensemble have a complete set of parameters,
    including those that were not updated.
    This is necessary because users can choose not to update parameters but may still want to analyse them.

    Parameters:
    all_parameter_groups (list[str]): A list of all parameter groups.
    updated_parameter_groups (list[str]): A list of parameter groups that have already been updated.
    iens_active_index (npt.NDArray[np.int_]): An array of indices for the active realizations in the
                                              target ensemble.
    source_ensemble (Ensemble): The file system of the source ensemble, from which parameters are copied.
    target_ensemble (Ensemble): The file system of the target ensemble, to which parameters are saved.

    Returns:
    None: The function does not return any value but updates the target file system by copying over
    the parameters.
    """
    # Identify parameter groups that have not been updated
    not_updated_parameter_groups = list(
        set(all_parameter_groups) - set(updated_parameter_groups)
    )

    # Copy the non-updated parameter groups from source to target for each active realization
    for parameter_group in not_updated_parameter_groups:
        for realization in iens_active_index:
            ds = source_ensemble.load_parameters(parameter_group, realization)
            target_ensemble.save_parameters(parameter_group, realization, ds)


def analysis_ES(
    parameters: Iterable[str],
    observations: Iterable[str],
    rng: np.random.Generator,
    module: ESSettings,
    alpha: float,
    std_cutoff: float,
    global_scaling: float,
    smoother_snapshot: SmootherSnapshot,
    ens_mask: npt.NDArray[np.bool_],
    source_ensemble: Ensemble,
    target_ensemble: Ensemble,
    progress_callback: Callable[[AnalysisEvent], None],
    auto_scale_observations: list[ObservationGroups] | None,
) -> None:
    iens_active_index = np.flatnonzero(ens_mask)

    ensemble_size = ens_mask.sum()

    def adaptive_localization_progress_callback(
        iterable: Sequence[T],
    ) -> TimedIterator[T]:
        return TimedIterator(iterable, progress_callback)

    progress_callback(AnalysisStatusEvent(msg="Loading observations and responses.."))
    (
        S,
        (
            observation_values,
            observation_errors,
            update_snapshot,
        ),
    ) = _load_observations_and_responses(
        source_ensemble,
        alpha,
        std_cutoff,
        global_scaling,
        iens_active_index,
        observations,
        auto_scale_observations,
        progress_callback,
    )
    num_obs = len(observation_values)

    smoother_snapshot.update_step_snapshots = update_snapshot

    if num_obs == 0:
        msg = "No active observations for update step"
        progress_callback(
            AnalysisErrorEvent(
                error_msg=msg,
                data=DataSection(
                    header=smoother_snapshot.header,
                    data=smoother_snapshot.csv,
                    extra=smoother_snapshot.extra,
                ),
            )
        )
        raise ErtAnalysisError(msg)

    smoother_es = ies.ESMDA(
        covariance=observation_errors**2,
        observations=observation_values,
        alpha=1,  # The user is responsible for scaling observation covariance (esmda usage)
        seed=rng,
        inversion=module.inversion,
    )
    truncation = module.enkf_truncation

    if module.localization:
        smoother_adaptive_es = AdaptiveESMDA(
            covariance=observation_errors**2,
            observations=observation_values,
            seed=rng,
        )

        # Pre-calculate cov_YY
        cov_YY = np.atleast_2d(np.cov(S))

        D = smoother_adaptive_es.perturb_observations(
            ensemble_size=ensemble_size, alpha=1.0
        )

    else:
        # Compute transition matrix so that
        # X_posterior = X_prior @ T
        try:
            T = smoother_es.compute_transition_matrix(
                Y=S, alpha=1.0, truncation=truncation
            )
        except scipy.linalg.LinAlgError as err:
            msg = (
                "Failed while computing transition matrix, "
                f"this might be due to outlier values in one or more realizations: {err}"
            )
            progress_callback(
                AnalysisErrorEvent(
                    error_msg=msg,
                    data=DataSection(
                        header=smoother_snapshot.header,
                        data=smoother_snapshot.csv,
                        extra=smoother_snapshot.extra,
                    ),
                )
            )
            raise ErtAnalysisError(msg) from err
        # Add identity in place for fast computation
        np.fill_diagonal(T, T.diagonal() + 1)

    def correlation_callback(
        cross_correlations_of_batch: npt.NDArray[np.float64],
        cross_correlations_accumulator: list[npt.NDArray[np.float64]],
    ) -> None:
        cross_correlations_accumulator.append(cross_correlations_of_batch)

    for param_group in parameters:
        param_ensemble_array = _load_param_ensemble_array(
            source_ensemble, param_group, iens_active_index
        )
        if module.localization:
            config_node = source_ensemble.experiment.parameter_configuration[
                param_group
            ]
            num_params = param_ensemble_array.shape[0]
            batch_size = _calculate_adaptive_batch_size(num_params, num_obs)
            batches = _split_by_batchsize(np.arange(0, num_params), batch_size)

            log_msg = f"Running localization on {num_params} parameters, {num_obs} responses, {ensemble_size} realizations and {len(batches)} batches"
            logger.info(log_msg)
            progress_callback(AnalysisStatusEvent(msg=log_msg))

            start = time.time()
            cross_correlations: list[npt.NDArray[np.float64]] = []
            for param_batch_idx in batches:
                X_local = param_ensemble_array[param_batch_idx, :]
                if isinstance(config_node, GenKwConfig):
                    correlation_batch_callback = functools.partial(
                        correlation_callback,
                        cross_correlations_accumulator=cross_correlations,
                    )
                else:
                    correlation_batch_callback = None
                param_ensemble_array[param_batch_idx, :] = (
                    smoother_adaptive_es.assimilate(
                        X=X_local,
                        Y=S,
                        D=D,
                        alpha=1.0,  # The user is responsible for scaling observation covariance (esmda usage)
                        correlation_threshold=module.correlation_threshold,
                        cov_YY=cov_YY,
                        progress_callback=adaptive_localization_progress_callback,
                        correlation_callback=correlation_batch_callback,
                    )
                )

            if cross_correlations:
                assert isinstance(config_node, GenKwConfig)
                parameter_names = [
                    t["name"]  # type: ignore
                    for t in config_node.transform_function_definitions
                ]
                cross_correlations_ = np.vstack(cross_correlations)
                if cross_correlations_.size != 0:
                    source_ensemble.save_cross_correlations(
                        cross_correlations_,
                        param_group,
                        parameter_names[: cross_correlations_.shape[0]],
                    )
            logger.info(
                f"Adaptive Localization of {param_group} completed in {(time.time() - start) / 60} minutes"
            )

        else:
            # In-place multiplication is not yet supported, therefore avoiding @=
            param_ensemble_array = param_ensemble_array @ T.astype(  # noqa: PLR6104
                param_ensemble_array.dtype
            )

        log_msg = f"Storing data for {param_group}.."
        logger.info(log_msg)
        progress_callback(AnalysisStatusEvent(msg=log_msg))
        start = time.time()

        _save_param_ensemble_array_to_disk(
            target_ensemble, param_ensemble_array, param_group, iens_active_index
        )
        logger.info(
            f"Storing data for {param_group} completed in {(time.time() - start) / 60} minutes"
        )

        _copy_unupdated_parameters(
            list(source_ensemble.experiment.parameter_configuration.keys()),
            parameters,
            iens_active_index,
            source_ensemble,
            target_ensemble,
        )


def _create_smoother_snapshot(
    prior_name: str,
    posterior_name: str,
    update_settings: UpdateSettings,
    global_scaling: float,
) -> SmootherSnapshot:
    return SmootherSnapshot(
        source_ensemble_name=prior_name,
        target_ensemble_name=posterior_name,
        alpha=update_settings.alpha,
        std_cutoff=update_settings.std_cutoff,
        global_scaling=global_scaling,
        update_step_snapshots=[],
    )


def smoother_update(
    prior_storage: Ensemble,
    posterior_storage: Ensemble,
    observations: Iterable[str],
    parameters: Iterable[str],
    update_settings: UpdateSettings,
    es_settings: ESSettings,
    rng: np.random.Generator | None = None,
    progress_callback: Callable[[AnalysisEvent], None] | None = None,
    global_scaling: float = 1.0,
) -> SmootherSnapshot:
    if not progress_callback:
        progress_callback = noop_progress_callback
    if rng is None:
        rng = np.random.default_rng()

    ens_mask = prior_storage.get_realization_mask_with_responses()

    smoother_snapshot = _create_smoother_snapshot(
        prior_storage.name,
        posterior_storage.name,
        update_settings,
        global_scaling,
    )

    try:
        analysis_ES(
            parameters,
            observations,
            rng,
            es_settings,
            update_settings.alpha,
            update_settings.std_cutoff,
            global_scaling,
            smoother_snapshot,
            ens_mask,
            prior_storage,
            posterior_storage,
            progress_callback,
            update_settings.auto_scale_observations,
        )
    except Exception as e:
        progress_callback(
            AnalysisErrorEvent(
                error_msg=str(e),
                data=DataSection(
                    header=smoother_snapshot.header,
                    data=smoother_snapshot.csv,
                    extra=smoother_snapshot.extra,
                ),
            )
        )
        raise e
    progress_callback(
        AnalysisCompleteEvent(
            data=DataSection(
                header=smoother_snapshot.header,
                data=smoother_snapshot.csv,
                extra=smoother_snapshot.extra,
            )
        )
    )
    return smoother_snapshot
