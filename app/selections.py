from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NodeVersion, Selection, SelectionItem, Version
from app.schemas import (SelectionCreate, SelectionItemOut, SelectionOut,
                         SelectionSummary)

router = APIRouter(prefix="/selections", tags=["selections"])


def pinned_rows(db, selection_id):
    """The exact saved rows of a selection, in document order."""
    return db.execute(
        select(SelectionItem, NodeVersion)
        .join(NodeVersion, NodeVersion.id == SelectionItem.node_version_id)
        .where(SelectionItem.selection_id == selection_id)
        .order_by(SelectionItem.version_number, NodeVersion.position)).all()


def selection_text(db, selection_id):
    """Rebuild the text of a selection from the pinned rows (used for the LLM)."""
    parts = []
    for item, node in pinned_rows(db, selection_id):
        parts.append(f"[Manual v{item.version_number}, section {node.number}: "
                     f"{node.title}]\n{node.body}")
    return "\n\n".join(parts)


def load_selection(db, selection_id):
    sel = db.get(Selection, selection_id)
    if sel is None:
        raise HTTPException(404, f"Selection {selection_id} not found")
    newest = db.scalar(select(func.max(Version.number)))
    items = []
    for item, node in pinned_rows(db, selection_id):
        latest = db.execute(
            select(NodeVersion, Version.number)
            .join(Version, Version.id == NodeVersion.version_id)
            .where(NodeVersion.logical_id == item.logical_id)
            .order_by(Version.number.desc())).first()
        latest_node, latest_num = latest
        if latest_num < newest:
            status = "removed_in_latest"
        elif latest_node.content_hash != item.content_hash:
            status = "changed"
        else:
            status = "current"
        items.append(SelectionItemOut(
            node_version_id=node.id, logical_id=item.logical_id,
            version=item.version_number, number=node.number, title=node.title,
            body=node.body, content_hash=item.content_hash, latest_status=status))
    return SelectionOut(id=sel.id, name=sel.name, created_at=sel.created_at, items=items)


@router.post("", response_model=SelectionOut, status_code=201)
def create_selection(payload: SelectionCreate, db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(payload.node_ids))   # remove repeats, keep order
    rows = {r.id: r for r in db.scalars(
        select(NodeVersion).where(NodeVersion.id.in_(ids))).all()}
    missing = [i for i in ids if i not in rows]
    if missing:                                    # nothing is saved if any id is wrong
        raise HTTPException(404, f"Node ids not found: {missing}")
    versions = {v.id: v.number for v in db.scalars(select(Version)).all()}
    sel = Selection(name=payload.name)
    db.add(sel)
    db.flush()
    for i in ids:
        r = rows[i]
        db.add(SelectionItem(
            selection_id=sel.id, node_version_id=r.id, logical_id=r.logical_id,
            version_number=versions[r.version_id], content_hash=r.content_hash))
    db.commit()
    return load_selection(db, sel.id)


@router.get("", response_model=list[SelectionSummary])
def list_selections(db: Session = Depends(get_db)):
    out = []
    for s in db.scalars(select(Selection).order_by(Selection.id)).all():
        count = db.scalar(select(func.count()).select_from(SelectionItem)
                          .where(SelectionItem.selection_id == s.id))
        out.append(SelectionSummary(id=s.id, name=s.name,
                                    created_at=s.created_at, item_count=count))
    return out


@router.get("/{selection_id}", response_model=SelectionOut)
def read_selection(selection_id: int, db: Session = Depends(get_db)):
    return load_selection(db, selection_id)