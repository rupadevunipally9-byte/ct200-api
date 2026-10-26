from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

class NodeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    logical_id: int
    number: str
    title: str
    level: int
    change_status: str


class NodeDetail(NodeSummary):
    version: int
    page: int
    parent_id: int | None
    body: str
    content_hash: str
    children: list[NodeSummary]


class VersionInfo(BaseModel):
    number: int
    source_file: str
    node_count: int


class SectionList(BaseModel):
    version: int
    sections: list[NodeSummary]


class SearchResult(BaseModel):
    version: int
    query: str
    results: list[NodeSummary]


class HistoryItem(BaseModel):
    version: int
    node_id: int
    number: str
    title: str
    content_hash: str


class DiffItem(BaseModel):
    type: str
    old: str
    new: str


class StepChange(BaseModel):
    from_version: int
    to_version: int
    changed: bool
    numbers_changed: bool
    summary: list[DiffItem]
    more: int


class ChangeReport(BaseModel):
    node_id: int
    logical_id: int
    changed_across_versions: bool
    history: list[HistoryItem]
    changes: list[StepChange]
class SelectionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    node_ids: list[int] = Field(min_length=1)


class SelectionItemOut(BaseModel):
    node_version_id: int
    logical_id: int
    version: int
    number: str
    title: str
    body: str                  # the exact pinned text
    content_hash: str
    latest_status: str         # current / changed / removed_in_latest


class SelectionOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    items: list[SelectionItemOut]


class SelectionSummary(BaseModel):
    id: int
    name: str
    created_at: datetime
    item_count: int