from __future__ import annotations

import datetime
from enum import Enum
import logging
from collections import defaultdict
from contextlib import ExitStack, suppress
from typing import Any, List, Mapping, Sequence

from dateutil import tz
from qtpy.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    Qt,
    QPersistentModelIndex,
)
from qtpy.QtGui import QColor

from ert.ensemble_evaluator import PartialSnapshot, Snapshot, state
from ert.gui.model.node import BaseGroup, IterNode, RealNode, RootNode, StepNode

logger = logging.getLogger(__name__)


RealStatusColorHint = Qt.ItemDataRole.UserRole + 3
ProgressRole = Qt.ItemDataRole.UserRole + 5
FileRole = Qt.ItemDataRole.UserRole + 6
RealIens = Qt.ItemDataRole.UserRole + 7
IterNum = Qt.ItemDataRole.UserRole + 12

# Indicates what type the underlying data is
StatusRole = Qt.ItemDataRole.UserRole + 11

SORTED_REALIZATION_IDS = "_sorted_real_ids"
SORTED_JOB_IDS = "_sorted_forward_model_ids"
REAL_JOB_STATUS_AGGREGATED = "_aggr_job_status_colors"
REAL_STATUS_COLOR = "_real_status_colors"

_QCOLORS: dict[tuple[int, int, int], QColor] = {
    state.COLOR_WAITING: QColor(*state.COLOR_WAITING),
    state.COLOR_PENDING: QColor(*state.COLOR_PENDING),
    state.COLOR_RUNNING: QColor(*state.COLOR_RUNNING),
    state.COLOR_FAILED: QColor(*state.COLOR_FAILED),
    state.COLOR_UNKNOWN: QColor(*state.COLOR_UNKNOWN),
    state.COLOR_FINISHED: QColor(*state.COLOR_FINISHED),
    state.COLOR_NOT_ACTIVE: QColor(*state.COLOR_NOT_ACTIVE),
}


class SnapshotModel(QAbstractItemModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.root = RootNode()

    @staticmethod
    def prerender(
        snapshot: Snapshot | PartialSnapshot,
    ) -> Snapshot | PartialSnapshot | None:
        """Pre-render some data that is required by this model. Ideally, this
        is called outside the GUI thread. This is a requirement of the model,
        so it has to be called."""

        reals = snapshot.reals
        forward_model_states = snapshot.get_forward_model_status_for_all_reals()
        if not reals and not forward_model_states:
            return None

        metadata: dict[str, Any] = {
            # A mapping from real to job to that job's QColor status representation
            REAL_JOB_STATUS_AGGREGATED: defaultdict(dict),
            # A mapping from real to that real's QColor status representation
            REAL_STATUS_COLOR: defaultdict(dict),
        }

        for real_id, real in reals.items():
            if real.status:
                metadata[REAL_STATUS_COLOR][real_id] = _QCOLORS[
                    state.REAL_STATE_TO_COLOR[real.status]
                ]

        is_snapshot = isinstance(snapshot, Snapshot)
        if is_snapshot:
            metadata[SORTED_REALIZATION_IDS] = sorted(snapshot.reals.keys(), key=int)
            metadata[SORTED_JOB_IDS] = defaultdict(list)
        for (
            real_id,
            forward_model_id,
        ), forward_model_status in forward_model_states.items():
            if is_snapshot:
                metadata[SORTED_JOB_IDS][real_id].append(forward_model_id)
            color = _QCOLORS[state.FORWARD_MODEL_STATE_TO_COLOR[forward_model_status]]
            metadata[REAL_JOB_STATUS_AGGREGATED][real_id][forward_model_id] = color

        if is_snapshot:
            snapshot.merge_metadata(metadata)
        elif isinstance(snapshot, PartialSnapshot):
            snapshot.update_metadata(metadata)
        return snapshot

    def _add_partial_snapshot(self, partial: PartialSnapshot, iter_: int) -> None:
        metadata = partial.metadata
        if not metadata:
            logger.debug("no metadata in partial, ignoring partial")
            return

        if iter_ not in self.root.children:
            logger.debug("no full snapshot yet, ignoring partial")
            return

        job_infos = partial.get_all_forward_models()
        if not partial.reals and not job_infos:
            logger.debug(f"no realizations in partial for iter {iter_}")
            return

        # Stack onto which we push change events for entities, since we branch
        # the code based on what is in the partial. This way we're guaranteed
        # that the change events will be emitted when the stack is unwound.
        with ExitStack() as stack:
            iter_node = self.root.children[iter_]
            iter_index = self.index(iter_node.index, 0, QModelIndex())
            iter_index_bottom_right = self.index(
                iter_node.index, iter_index.column(), QModelIndex()
            )
            stack.callback(self.dataChanged.emit, iter_index, iter_index_bottom_right)

            reals_changed: List[int] = []

            for real_id in partial.get_real_ids():
                real_node = iter_node.children[real_id]
                real = partial.get_real(real_id)
                if real and real.status:
                    real_node.status = real.status
                for real_forward_model_id, color in (
                    metadata[REAL_JOB_STATUS_AGGREGATED].get(real_id, {}).items()
                ):
                    real_node.real_job_status_aggregated[real_forward_model_id] = color
                if real_id in metadata[REAL_STATUS_COLOR]:
                    real_node.status_color = metadata[REAL_STATUS_COLOR][real_id]
                reals_changed.append(real_node.index)

            jobs_changed_by_real: Mapping[str, Sequence[int]] = defaultdict(list)

            for (
                real_id,
                forward_model_id,
            ), job in partial.get_all_forward_models().items():
                real_node = iter_node.children[real_id]
                job_node = real_node.children[forward_model_id]

                jobs_changed_by_real[real_id].append(job_node.index)

                if job.status:
                    job_node.status = job.status
                if job.start_time:
                    job_node.start_time = job.start_time
                if job.end_time:
                    job_node.end_time = job.end_time
                if job.stdout:
                    job_node.stdout = job.stdout
                if job.stderr:
                    job_node.stderr = job.stderr
                if job.index:
                    job_node.index_ = job.index
                if job.current_memory_usage:
                    job_node.current_memory_usage = int(job.current_memory_usage)
                if job.max_memory_usage:
                    job_node.max_memory_usage = int(job.max_memory_usage)

                # Errors may be unset as the queue restarts the job
                job_node.error = job.error if job.error else ""

            for real_idx, changed_jobs in jobs_changed_by_real.items():
                real_node = iter_node.children[real_idx]
                real_index = self.index(real_node.index, 0, iter_index)

                job_top_left = self.index(min(changed_jobs), 0, real_index)
                job_bottom_right = self.index(
                    max(changed_jobs),
                    self.columnCount(real_index) - 1,
                    real_index,
                )
                stack.callback(self.dataChanged.emit, job_top_left, job_bottom_right)

            if reals_changed:
                real_top_left = self.index(min(reals_changed), 0, iter_index)
                real_bottom_right = self.index(
                    max(reals_changed), self.columnCount(iter_index) - 1, iter_index
                )
                stack.callback(self.dataChanged.emit, real_top_left, real_bottom_right)

            return

    def _add_snapshot(self, snapshot: Snapshot, iter_: int):
        metadata = snapshot.metadata
        snapshot_tree = IterNode(
            parent=self.root,
            id=iter_,
            status=snapshot.status or "",
            sorted_realization_ids=metadata[SORTED_REALIZATION_IDS],
            sorted_job_ids=metadata[SORTED_JOB_IDS],
        )
        for real_id in snapshot_tree.sorted_realization_ids:
            real = snapshot.get_real(real_id)
            real_node = RealNode(
                parent=snapshot_tree,
                status=real.status or "",
                active=real.active or False,
                real_job_status_aggregated=metadata[REAL_JOB_STATUS_AGGREGATED][
                    real_id
                ],
                status_color=metadata[REAL_STATUS_COLOR][real_id],
            )
            snapshot_tree.children[real_id] = real_node

            for forward_model_id in metadata[SORTED_JOB_IDS][real_id]:
                step = snapshot.get_job(real_id, forward_model_id)
                step_node = StepNode(
                    parent=real_node,
                    id=forward_model_id,
                )
                real_node.children[forward_model_id] = step_node

        if iter_ in self.root.children:
            self.modelAboutToBeReset.emit()
            self.root.children[iter_] = snapshot_tree
            snapshot_tree.parent = self.root
            self.modelReset.emit()
            return

        parent = QModelIndex()
        next_iter = len(self.root.children)
        self.beginInsertRows(parent, next_iter, next_iter)
        self.rowsInserted.emit(parent, snapshot_tree.index, snapshot_tree.index)

    def columnCount(self, parent: QModelIndex = ...) -> int:
        item = parent.internalPointer()
        if isinstance(item, BaseGroup):
            return len(item)
        return 0

    def rowCount(self, parent: QModelIndex = ...) -> int:
        if parent.column() > 0:
            return 0
        item = parent.internalPointer() if parent.isValid() else self.root
        return len(getattr(item, "children", ()))

    def parent(self, child: QModelIndex | QPersistentModelIndex) -> QModelIndex:
        if not child.isValid():
            return QModelIndex()

        item = child.internalPointer()
        if isinstance(item, (IterNode, RealNode, StepNode)):
            return self.createIndex(item.index, 0, item)
        return QModelIndex()

    def data(self, index: QModelIndex, role: Qt.ItemDataRole) -> Any:
        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

        if not isinstance((node := index.internalPointer()), BaseGroup):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return node.display(index.column())
        if role == Qt.ItemDataRole.TooltipRole:
            return node.tooltip(index.column())
        return None

    def index(
        self, row: int, column: int, parent: QModelIndex | QPersistentModelIndex = ...
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        item = self.root if not parent.isValid() else parent.internalPointer()
        with suppress(KeyError):
            if isinstance(item, (RootNode, IterNode, RealNode)):
                return self.createIndex(row, column, list(item.children.values())[row])
        return QModelIndex()

    def reset(self) -> None:
        self.modelAboutToBeReset.emit()
        self.root = RootNode()
        self.modelReset.emit()
