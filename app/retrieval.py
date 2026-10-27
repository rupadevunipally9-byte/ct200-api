from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.generations import get_store
from app.models import NodeVersion, Selection, Version
from app.staleness import GenerationView, build_view
from app.store import JsonStore

router = APIRouter(tags=["retrieval"])


def target_version(db, number):
    if number is None:
        v = db.scalars(select(Version).order_by(Version.number.desc())).first()
    else:
        v = db.scalars(select(Version).where(Version.number == number)).first()
    if v is None:
        raise HTTPException(404, "Version not found")
    return v


def ok_only(docs):
    return [d for d in docs if d["status"] == "ok"]


@router.get("/generations/{generation_id}", response_model=GenerationView)
def read_generation(generation_id: str, against_version: int | None = None,
                    db: Session = Depends(get_db), store: JsonStore = Depends(get_store)):
    doc = store.get(generation_id)
    if doc is None or doc["status"] != "ok":
        raise HTTPException(404, "Generation not found")
    return build_view(db, doc, target_version(db, against_version))


@router.get("/selections/{selection_id}/generations", response_model=list[GenerationView])
def selection_generations(selection_id: int, against_version: int | None = None,
                          db: Session = Depends(get_db),
                          store: JsonStore = Depends(get_store)):
    if db.get(Selection, selection_id) is None:
        raise HTTPException(404, f"Selection {selection_id} not found")
    target = target_version(db, against_version)
    return [build_view(db, d, target) for d in ok_only(store.find(selection_id=selection_id))]


@router.get("/nodes/{node_id}/generations", response_model=list[GenerationView])
def node_generations(node_id: int, against_version: int | None = None,
                     db: Session = Depends(get_db), store: JsonStore = Depends(get_store)):
    node = db.get(NodeVersion, node_id)
    if node is None:
        raise HTTPException(404, f"Node {node_id} not found")
    target = target_version(db, against_version)
    views = []
    for d in ok_only(store.find(logical_id=node.logical_id)):
        view = build_view(db, d, target, only_logical=node.logical_id)
        if view.test_cases:       # only test cases that cite this section
            views.append(view)
    return views