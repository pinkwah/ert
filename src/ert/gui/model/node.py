from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path

from typing import Any, ClassVar, Final
from dataclasses import dataclass, field
from functools import cache, cached_property
from ert.ensemble_evaluator import state


from qtpy.QtGui import QColor


COLOR_WAITING: Final[QColor] = QColor(*state.COLOR_WAITING)
COLOR_PENDING: Final[QColor] = QColor(*state.COLOR_PENDING)
COLOR_RUNNING: Final[QColor] = QColor(*state.COLOR_RUNNING)


def _estimate_duration(
    start_time: datetime.datetime, end_time: datetime.datetime | None = None
) -> datetime.timedelta:
    timezone = None
    if start_time.tzname() is not None:
        timezone = tz.gettz(start_time.tzname())
    end_time = end_time or datetime.datetime.now(timezone)
    return end_time - start_time


class BaseGroup:
    __columns__: ClassVar[list[tuple[str, str]]]

    def get(self, index: int) -> Any:
        return getattr(self, self.__columns__[index][0])

    @classmethod
    def header(cls, index: int) -> str:
        return cls.__columns__[index][1]

    def display(self, index: int) -> str | None:
        if (attr := getattr(self, self.__columns__[index][0], None)) is None:
            return None
        return str(attr)

    def tooltip(self, index: int) -> str | None:
        name = f"{self.__columns__[index][0]}_tooltip"
        if (attr := getattr(self, name, None)) is None:
            return None
        return str(attr)

    @classmethod
    def __len__(cls) -> int:
        return len(cls.__columns__)


@dataclass
class RootNode:
    children: dict[int, IterNode] = field(default_factory=dict)


@dataclass
class IterNode(BaseGroup):
    __columns__ = [
        ("name", "Name"),
        ("status", "Status"),
    ]

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
class RealNode(BaseGroup):
    __columns__ = [
        ("name", "Name"),
        ("status", "Status"),
        ("active", "Active"),
    ]

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
                self.real_job_status_aggregated[forward_model_id] == COLOR_PENDING
                and self.status_color == COLOR_WAITING
                and not is_running
            ):
                colors.append(COLOR_WAITING)
            else:
                colors.append(self.real_job_status_aggregated[forward_model_id])

        return colors


@dataclass
class StepNode(BaseGroup):
    __columns__ = [
        ("name", "Name"),
        ("duration", "Duration"),
        ("error", "Error"),
        ("status", "Status"),
        ("stdout", "STDOUT"),
        ("stderr", "STDERR"),
        ("current_memory_usage", "Current memory usage"),
        ("max_memory_usage", "Max memory usage"),
    ]

    parent: RealNode

    id: str

    status: str | None = None
    data: str | None = None
    stdout: Path | None = None
    stderr: Path | None = None
    current_memory_usage: int | None = None
    error: str | None = None
    max_memory_usage: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")

    @property
    def error_tooltip(self) -> str | None:
        return self.error

    @property
    def duration(self) -> str | None:
        if (start_time := self.start_time) is None:
            return None
        delta = _estimate_duration(start_time, self.end_time)
        # There is no method for truncating microseconds, so we remove them
        delta -= timedelta(microseconds=delta.microseconds)
        return str(delta)

    @property
    def duration_tooltip(self) -> str | None:
        if (start_time := self.start_time) is None:
            return None
        delta = _estimate_duration(start_time, self.end_time)
        return f"Start time: {str(start_time)}\nDuration: {str(delta)}"
