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


def node_id(client, number, version):
    hits = client.get("/search", params={"q": "", "version": version}).json()["results"]
    return next(h["id"] for h in hits if h["number"] == number)


def test_selection_keeps_old_version_text_after_reingest(client):
    nid = node_id(client, "2.1.1.1", 1)
    r = client.post("/selections", json={"name": "battery v1", "node_ids": [nid]})
    assert r.status_code == 201
    item = r.json()["items"][0]
    assert item["version"] == 1
    assert "300 measurement cycles" in item["body"]      # old text, not v2's 250
    assert item["latest_status"] == "changed"            # but we are told it changed


def test_selection_on_unchanged_node_is_current(client):
    nid = node_id(client, "1.1", 2)
    item = client.post("/selections", json={"name": "intro", "node_ids": [nid]}).json()["items"][0]
    assert item["latest_status"] == "current"


def test_repeated_ids_are_saved_once(client):
    nid = node_id(client, "3.2", 2)
    r = client.post("/selections", json={"name": "dup", "node_ids": [nid, nid, nid]})
    assert len(r.json()["items"]) == 1


def test_unknown_id_is_rejected_and_nothing_is_saved(client):
    before = len(client.get("/selections").json())
    nid = node_id(client, "4.1", 2)
    r = client.post("/selections", json={"name": "bad", "node_ids": [nid, 99999]})
    assert r.status_code == 404
    assert len(client.get("/selections").json()) == before


def test_empty_selection_and_empty_name_are_rejected(client):
    assert client.post("/selections", json={"name": "x", "node_ids": []}).status_code == 422
    assert client.post("/selections", json={"name": "  ", "node_ids": [1]}).status_code == 422


def test_read_selection_back(client):
    nid = node_id(client, "4.2", 1)
    sid = client.post("/selections", json={"name": "errors v1", "node_ids": [nid]}).json()["id"]
    got = client.get(f"/selections/{sid}").json()
    assert got["name"] == "errors v1" and "within 2 seconds" in got["items"][0]["body"]
    assert client.get("/selections/99999").status_code == 404