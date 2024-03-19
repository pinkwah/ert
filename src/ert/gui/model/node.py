from __future__ import annotations
from datetime import datetime

from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from functools import cached_property


if TYPE_CHECKING:
    from qtpy.QtGui import QColor


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
    real_status_color: QColor

    children: dict[str, StepNode] = field(default_factory=dict)

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")

@dataclass
class StepNode:
    parent: RealNode

    id: str
    index_: str

    status: str | None = None
    data: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    current_memory_usage: str | None = None
    error: str | None = None
    max_memory_usage: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    @cached_property
    def index(self) -> int:
        for index, id_ in enumerate(self.parent.children):
            if id_ == self.id:
                return index
        raise IndexError(f"Could not find iter {self.id} in {self.parent}")
