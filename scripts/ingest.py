import sys
from collections import Counter

sys.path.insert(0, ".")
from sqlalchemy import select

from app import models
from app.db import Base, SessionLocal, engine
from app.ingest import ingest_pdf

Base.metadata.create_all(engine)

with SessionLocal() as db:
    try:
        v = ingest_pdf(db, sys.argv[1])
    except ValueError as e:
        db.rollback()
        print("STOPPED:", e)
        sys.exit(1)
    rows = db.scalars(
        select(models.NodeVersion)
        .where(models.NodeVersion.version_id == v.id)
        .order_by(models.NodeVersion.position)
    ).all()
    print(f"Ingested {v.source_file} as version {v.number}: {len(rows)} nodes")
    print(dict(Counter(r.change_status for r in rows)))
    for r in rows:
        if r.change_status in ("changed", "added"):
            print(f"  {r.change_status.upper():8} {r.number:8} {r.title}  (matched by: {r.match_method})")