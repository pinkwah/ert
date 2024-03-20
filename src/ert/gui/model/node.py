from __future__ import annotations
from datetime import datetime

from typing import Final
from dataclasses import dataclass, field
from functools import cached_property
from ert.ensemble_evaluator import state


from qtpy.QtGui import QColor


COLOR_WAITING: Final[QColor] = QColor(*state.COLOR_WAITING)
COLOR_PENDING: Final[QColor] = QColor(*state.COLOR_PENDING)
COLOR_RUNNING: Final[QColor] = QColor(*state.COLOR_RUNNING)


@dataclass
class RootNode:
    children: dict[int, IterNode] = field(default_factory=dict)

@dataclass
class IterNode:
    parent: RootNode
    id: int
    status: str
    sorted_realization_ids: list[str]
    sorted_job_ids: list[str]

    children: dict[str, RealNode] = field(default_factory=dict)

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")

@dataclass
class RealNode:
    parent: IterNode

    id: int

    status: str
    active: bool
    real_job_status_aggregated: dict[str, QColor]
    status_color: QColor

    children: dict[str, StepNode] = field(default_factory=dict)

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")

    def color_hints(self) -> list[QColor]:
        colors: list[QColor] = []

        is_running = False

        if COLOR_RUNNING in self.real_job_status_aggregated.values():
            is_running = True

        for forward_model_id in self.parent.sorted_job_ids[self.id]:
            # if queue system status is WAIT, jobs should indicate WAIT
            if (
                self.real_job_status_aggregated[forward_model_id]
                == COLOR_PENDING
                and self.status_color == COLOR_WAITING
                and not is_running
            ):
                colors.append(COLOR_WAITING)
            else:
                colors.append(
                    self.real_job_status_aggregated[forward_model_id]
                )

        return colors

@dataclass
class StepNode:
    parent: RealNode

    id: str
    index_: str

    status: str | None = None
    data: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    current_memory_usage: float | None = None
    error: str | None = None
    max_memory_usage: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")

    @property
    def curmem(self) -> float | None:
        return self.current_memory_usage

    @property
    def maxmem(self) -> float | None:
        return self.max_memory_usage
