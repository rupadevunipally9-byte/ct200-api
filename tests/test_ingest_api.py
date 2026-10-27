import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app, get_db


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ingest_v1_then_v2_through_the_api(client):
    r1 = client.post("/versions", json={"file": "ct200_manual.pdf"})
    assert r1.status_code == 201
    assert r1.json() == {"number": 1, "source_file": "ct200_manual.pdf", "node_count": 28}
    r2 = client.post("/versions", json={"file": "ct200_manual_v2.pdf"})
    assert r2.status_code == 201 and r2.json()["number"] == 2 and r2.json()["node_count"] == 29
    assert [v["number"] for v in client.get("/versions").json()] == [1, 2]


def test_same_file_twice_is_a_409_and_creates_nothing(client):
    client.post("/versions", json={"file": "ct200_manual.pdf"})
    again = client.post("/versions", json={"file": "ct200_manual.pdf"})
    assert again.status_code == 409 and "already ingested" in again.json()["detail"]
    assert len(client.get("/versions").json()) == 1


@pytest.mark.parametrize("name", ["nope.pdf", "../README.md", "ct200_manual.txt"])
def test_unknown_or_unsafe_file_names_are_rejected(client, name):
    assert client.post("/versions", json={"file": name}).status_code == 404