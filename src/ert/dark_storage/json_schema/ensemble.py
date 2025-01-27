from typing import Any, List, Mapping, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class _Ensemble(BaseModel):
    size: int
    active_realizations: List[int] = []


class EnsembleIn(_Ensemble):
    update_id: Optional[UUID] = None
    userdata: Mapping[str, Any] = {}


class EnsembleOut(_Ensemble):
    id: UUID
    children: List[UUID] = Field(alias="child_ensemble_ids")
    parent: Optional[UUID] = Field(None, alias="parent_ensemble_id")
    experiment_id: Optional[UUID] = None
    userdata: Mapping[str, Any]

    class Config:
        from_attributes = True
