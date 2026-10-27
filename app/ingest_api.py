from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest import AlreadyIngested, ingest_pdf
from app.models import NodeVersion
from app.schemas import VersionInfo

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
router = APIRouter(tags=["ingestion"])


class IngestRequest(BaseModel):
    file: str   # name of a PDF inside the data/ folder, e.g. "ct200_manual_v2.pdf"


@router.post("/versions", response_model=VersionInfo, status_code=201)
def ingest(payload: IngestRequest, db: Session = Depends(get_db)):
    path = (DATA_DIR / payload.file).resolve()
    if path.parent != DATA_DIR or path.suffix.lower() != ".pdf" or not path.is_file():
        raise HTTPException(404, "File not found. Give the name of a PDF inside the data/ folder.")
    try:
        version = ingest_pdf(db, str(path))
    except AlreadyIngested as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    count = db.scalar(select(func.count()).select_from(NodeVersion)
                      .where(NodeVersion.version_id == version.id))
    return VersionInfo(number=version.number, source_file=version.source_file,
                       node_count=count)