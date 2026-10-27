from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base, engine, get_db
from app.diffing import diff_summary
from app.models import NodeVersion, Version
from app.schemas import (ChangeReport, HistoryItem, NodeDetail, NodeSummary,
                         SearchResult, SectionList, StepChange, VersionInfo)

Base.metadata.create_all(engine)
app = FastAPI(title="CT-200 Manual API")

from app.selections import router as selections_router  # noqa: E402

app.include_router(selections_router)

from app.generations import router as generations_router  # noqa: E402

app.include_router(generations_router)


def resolve_version(db, number):
    if number is None:
        v = db.scalars(select(Version).order_by(Version.number.desc())).first()
    else:
        v = db.scalars(select(Version).where(Version.number == number)).first()
    if v is None:
        raise HTTPException(404, "Version not found (has any PDF been ingested?)")
    return v
from app.retrieval import router as retrieval_router  # noqa: E402

app.include_router(retrieval_router)
from app.ingest_api import router as ingest_router  # noqa: E402

app.include_router(ingest_router)


def get_node(db, node_id):
    row = db.get(NodeVersion, node_id)
    if row is None:
        raise HTTPException(404, f"Node {node_id} not found")
    return row


@app.get("/versions", response_model=list[VersionInfo])
def list_versions(db: Session = Depends(get_db)):
    out = []
    for v in db.scalars(select(Version).order_by(Version.number)).all():
        count = db.scalar(select(func.count()).select_from(NodeVersion)
                          .where(NodeVersion.version_id == v.id))
        out.append(VersionInfo(number=v.number, source_file=v.source_file, node_count=count))
    return out


@app.get("/sections", response_model=SectionList)
def top_sections(version: int | None = None, db: Session = Depends(get_db)):
    v = resolve_version(db, version)
    rows = db.scalars(select(NodeVersion)
                      .where(NodeVersion.version_id == v.id, NodeVersion.level == 1)
                      .order_by(NodeVersion.position)).all()
    return SectionList(version=v.number,
                       sections=[NodeSummary.model_validate(r) for r in rows])


@app.get("/nodes/{node_id}", response_model=NodeDetail)
def read_node(node_id: int, db: Session = Depends(get_db)):
    row = get_node(db, node_id)
    v = db.get(Version, row.version_id)
    kids = db.scalars(select(NodeVersion).where(NodeVersion.parent_id == row.id)
                      .order_by(NodeVersion.position)).all()
    return NodeDetail(
        id=row.id, logical_id=row.logical_id, number=row.number, title=row.title,
        level=row.level, change_status=row.change_status, version=v.number,
        page=row.page, parent_id=row.parent_id, body=row.body,
        content_hash=row.content_hash,
        children=[NodeSummary.model_validate(k) for k in kids])


@app.get("/search", response_model=SearchResult)
def search(q: str, version: int | None = None,
           scope: Literal["all", "headings", "text"] = "all",
           db: Session = Depends(get_db)):
    v = resolve_version(db, version)
    pattern = f"%{q.strip()}%"
    cond = {"headings": NodeVersion.title.ilike(pattern),
            "text": NodeVersion.body.ilike(pattern),
            "all": NodeVersion.title.ilike(pattern) | NodeVersion.body.ilike(pattern)}[scope]
    rows = db.scalars(select(NodeVersion)
                      .where(NodeVersion.version_id == v.id, cond)
                      .order_by(NodeVersion.position)).all()
    return SearchResult(version=v.number, query=q,
                        results=[NodeSummary.model_validate(r) for r in rows])


@app.get("/nodes/{node_id}/changes", response_model=ChangeReport)
def node_changes(node_id: int, db: Session = Depends(get_db)):
    row = get_node(db, node_id)
    pairs = db.execute(
        select(NodeVersion, Version.number)
        .join(Version, Version.id == NodeVersion.version_id)
        .where(NodeVersion.logical_id == row.logical_id)
        .order_by(Version.number)).all()
    history = [HistoryItem(version=num, node_id=nv.id, number=nv.number,
                           title=nv.title, content_hash=nv.content_hash)
               for nv, num in pairs]
    changes = []
    for (old, old_num), (new, new_num) in zip(pairs, pairs[1:]):
        changed = old.content_hash != new.content_hash
        detail = diff_summary(old.body, new.body) if changed else \
            {"numbers_changed": False, "summary": [], "more": 0}
        changes.append(StepChange(from_version=old_num, to_version=new_num,
                                  changed=changed, **detail))
    return ChangeReport(node_id=row.id, logical_id=row.logical_id,
                        changed_across_versions=any(c.changed for c in changes),
                        history=history, changes=changes)