import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.ingest import ingest_pdf

V1 = "data/ct200_manual.pdf"
V2 = "data/ct200_manual_v2.pdf"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def nodes_of(db, version):
    rows = db.scalars(
        select(models.NodeVersion).where(models.NodeVersion.version_id == version.id)
    ).all()
    return {r.number: r for r in rows}


def test_v2_reuses_same_logical_nodes_and_flags_changes(db):
    a = nodes_of(db, ingest_pdf(db, V1))
    b = nodes_of(db, ingest_pdf(db, V2))
    for number in a:
        assert a[number].logical_id == b[number].logical_id   # not duplicated
    assert b["4.2"].logical_id != b["7.1"].logical_id          # two "Error Codes" stay separate
    changed = {n for n, r in b.items() if r.change_status == "changed"}
    assert changed == {"2.1.1.1", "3.2", "4.2", "4.3"}
    assert b["5.3"].change_status == "added"
    assert b["5.3"].logical_id not in {r.logical_id for r in a.values()}


def test_v1_is_not_destroyed_by_v2(db):
    v1 = ingest_pdf(db, V1)
    ingest_pdf(db, V2)
    a = nodes_of(db, v1)
    assert len(a) == 28
    assert "300 measurement cycles" in a["2.1.1.1"].body


def test_same_file_twice_is_refused(db):
    ingest_pdf(db, V1)
    with pytest.raises(ValueError):
        ingest_pdf(db, V1)