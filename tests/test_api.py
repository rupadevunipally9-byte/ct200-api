import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest import ingest_pdf
from app.main import app, get_db


@pytest.fixture(scope="module")
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        ingest_pdf(s, "data/ct200_manual.pdf")
        ingest_pdf(s, "data/ct200_manual_v2.pdf")

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def find(client, number, version=2):
    hits = client.get("/search", params={"q": "", "version": version}).json()["results"]
    return next(h for h in hits if h["number"] == number)


def test_sections_default_to_latest_version(client):
    data = client.get("/sections").json()
    assert data["version"] == 2 and len(data["sections"]) == 8
    assert client.get("/sections", params={"version": 1}).json()["version"] == 1


def test_node_detail_has_children_text_and_hash(client):
    sec2 = client.get(f"/nodes/{find(client, '2')['id']}").json()
    assert [c["number"] for c in sec2["children"]] == ["2.1", "2.2"]
    sec21 = client.get(f"/nodes/{find(client, '2.1')['id']}").json()
    assert [c["number"] for c in sec21["children"]] == ["2.1.1.1"]
    assert len(sec21["content_hash"]) == 64 and "Oscillometric" in sec21["body"]


def test_search_finds_text_cleaned_of_ligatures(client):
    hits = client.get("/search", params={"q": "profile", "scope": "text"}).json()["results"]
    assert {h["number"] for h in hits} >= {"3.1", "5.1"}


def test_duplicate_heading_search_returns_two_distinct_nodes(client):
    hits = client.get("/search", params={"q": "Error Codes", "scope": "headings"}).json()["results"]
    assert len(hits) == 2 and hits[0]["id"] != hits[1]["id"]


def test_changed_node_reports_diff(client):
    report = client.get(f"/nodes/{find(client, '2.1.1.1')['id']}/changes").json()
    assert report["changed_across_versions"] is True
    step = report["changes"][0]
    assert step["numbers_changed"] is True
    pairs = {(d["old"], d["new"]) for d in step["summary"]}
    assert any("300" in o and "250" in n for o, n in pairs)


def test_unchanged_node_reports_no_change(client):
    report = client.get(f"/nodes/{find(client, '1.1')['id']}/changes").json()
    assert report["changed_across_versions"] is False


def test_missing_things_return_404(client):
    assert client.get("/nodes/99999").status_code == 404
    assert client.get("/sections", params={"version": 9}).status_code == 404