from pydantic import BaseModel, ConfigDict


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