import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.generation import (PROMPT_VERSION, GenerationFailed, generate_test_cases)
from app.llm import LLMError, call_llm, model_name
from app.models import Selection
from app.schemas import GenerationOut
from app.selections import pinned_rows, selection_text
from app.store import JsonStore

router = APIRouter(tags=["generations"])


def get_llm():
    return call_llm


def get_store():
    return JsonStore(os.environ.get("STORE_DIR", "store"))


@router.post("/selections/{selection_id}/generate", response_model=GenerationOut,
             status_code=201)
def generate(selection_id: int, response: Response, force: bool = False,
             db: Session = Depends(get_db), llm=Depends(get_llm),
             store: JsonStore = Depends(get_store)):
    if db.get(Selection, selection_id) is None:
        raise HTTPException(404, f"Selection {selection_id} not found")

    pinned = pinned_rows(db, selection_id)
    source_text = selection_text(db, selection_id)
    sources = [{"node_version_id": node.id, "logical_id": item.logical_id,
                "version": item.version_number, "number": node.number,
                "title": node.title, "content_hash": item.content_hash}
               for item, node in pinned]
    allowed = {s["number"] for s in sources}
    input_hash = hashlib.sha256(f"{PROMPT_VERSION}\n{source_text}".encode()).hexdigest()

    if not force:  # same pinned text + same prompt = same input: reuse the saved result
        same = [g for g in store.find(selection_id=selection_id)
                if g["status"] == "ok" and g["input_hash"] == input_hash]
        if same:
            response.status_code = 200
            return {**same[-1], "reused": True}

    generation_id = uuid.uuid4().hex
    base = {"generation_id": generation_id, "selection_id": selection_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": model_name(), "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash, "sources": sources}
    try:
        cases, attempts = generate_test_cases(llm, source_text, allowed)
    except LLMError as e:
        raise HTTPException(502, f"AI service problem: {e}")
    except GenerationFailed as e:
        store.save({**base, "status": "failed", "attempts": len(e.failures),
                    "failures": e.failures, "test_cases": []})
        raise HTTPException(502, detail={
            "message": "The AI did not return a valid answer after all tries. "
                       "Nothing was saved as a result.",
            "generation_id": generation_id, "failures": e.failures})

    for i, case in enumerate(cases):
        case.test_case_id = f"{generation_id}:{i}"
    doc = {**base, "status": "ok", "attempts": attempts,
           "test_cases": [c.model_dump() for c in cases]}
    store.save(doc)
    return {**doc, "reused": False}