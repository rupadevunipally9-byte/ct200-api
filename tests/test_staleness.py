import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base
from app.generations import get_llm, get_store
from app.ingest import ingest_pdf
from app.main import app, get_db
from app.parser import content_hash
from app.store import JsonStore


def add_fake_v3(s, v2):
    """v3 = v2, but 1.1 has one reworded phrase and 6.2 is removed."""
    v3 = models.Version(document_id=v2.document_id, number=3,
                        source_file="fake_v3.pdf", file_sha256="fake")
    s.add(v3)
    s.flush()
    rows = s.scalars(select(models.NodeVersion)
                     .where(models.NodeVersion.version_id == v2.id)).all()
    for r in rows:
        if r.number == "6.2":
            continue
        body = r.body.replace("intended to", "designed to") if r.number == "1.1" else r.body
        s.add(models.NodeVersion(
            logical_id=r.logical_id, version_id=v3.id, number=r.number, title=r.title,
            level=r.level, position=r.position, page=r.page, parent_id=None, body=body,
            content_hash=content_hash(body),
            change_status="changed" if body != r.body else "unchanged",
            match_method="number+title"))
    s.commit()


def build_engine(with_v3):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ingest_pdf(s, "data/ct200_manual.pdf")
        v2 = ingest_pdf(s, "data/ct200_manual_v2.pdf")
        if with_v3:
            add_fake_v3(s, v2)
    return eng


@pytest.fixture(scope="module")
def engine2():
    return build_engine(False)


@pytest.fixture(scope="module")
def engine3():
    return build_engine(True)


class FakeLLM:
    def __init__(self):
        self.replies = []

    def __call__(self, messages):
        return self.replies.pop(0)


def start(engine, tmp_path):
    fake, store = FakeLLM(), JsonStore(tmp_path)

    def db_override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app), fake


@pytest.fixture()
def env2(engine2, tmp_path):
    yield start(engine2, tmp_path)
    app.dependency_overrides.clear()


@pytest.fixture()
def env3(engine3, tmp_path):
    yield start(engine3, tmp_path)
    app.dependency_overrides.clear()


def node_id(client, number, version):
    hits = client.get("/search", params={"q": "", "version": version}).json()["results"]
    return next(h["id"] for h in hits if h["number"] == number)


def reply(*section_lists):
    cases = [{"title": f"Test case number {i}", "objective": "Check the behaviour",
              "preconditions": ["Device is on"], "steps": ["Do the thing"],
              "expected_result": "The expected thing happens", "priority": "high",
              "source_sections": list(sec)} for i, sec in enumerate(section_lists)]
    return json.dumps({"test_cases": cases})


def generate(client, fake, numbers, sections_per_case, version=1):
    ids = [node_id(client, n, version) for n in numbers]
    sid = client.post("/selections", json={"name": "t", "node_ids": ids}).json()["id"]
    fake.replies = [reply(*sections_per_case)]
    r = client.post(f"/selections/{sid}/generate")
    assert r.status_code == 201, r.text
    return sid, r.json()


def by_title(view):
    return {tc["title"]: tc["staleness"] for tc in view["test_cases"]}


def test_numbers_changed_marks_stale_and_untouched_stays_current(env2):
    client, fake = env2
    sid, _ = generate(client, fake, ["4.1", "4.2"], [["4.1"], ["4.2"], ["4.1", "4.2"]])
    views = client.get(f"/selections/{sid}/generations").json()
    assert len(views) == 1
    g = views[0]
    assert by_title(g) == {"Test case number 0": "current",
                           "Test case number 1": "stale",
                           "Test case number 2": "stale"}
    assert g["overall_status"] == "stale" and g["checked_against_version"] == 2
    assert g["test_cases"][2]["stale_because"] == ["4.2"]
    src = {s["number"]: s for s in g["sources"]}
    assert src["4.1"]["status"] == "current"
    assert src["4.2"]["status"] == "stale" and src["4.2"]["numbers_changed"] is True
    assert any("1.5" in c["new"] for c in src["4.2"]["changes"])


def test_checking_against_the_pinned_version_is_all_current(env2):
    client, fake = env2
    sid, _ = generate(client, fake, ["4.2"], [["4.2"], ["4.2"], ["4.2"]])
    g = client.get(f"/selections/{sid}/generations", params={"against_version": 1}).json()[0]
    assert g["overall_status"] == "current"


def test_node_retrieval_returns_only_citing_cases_for_any_version_of_the_node(env2):
    client, fake = env2
    generate(client, fake, ["4.1", "4.2"], [["4.1"], ["4.2"], ["4.1", "4.2"]])
    for version in (1, 2):   # the v1 row and the v2 row are the same logical section
        nid = node_id(client, "4.2", version)
        views = client.get(f"/nodes/{nid}/generations").json()
        assert len(views) == 1
        assert set(by_title(views[0])) == {"Test case number 1", "Test case number 2"}
    nid = node_id(client, "4.1", 1)
    cases = client.get(f"/nodes/{nid}/generations").json()[0]["test_cases"]
    assert {c["title"] for c in cases} == {"Test case number 0", "Test case number 2"}


def test_read_by_generation_id_and_unknown_ids(env2):
    client, fake = env2
    _, gen = generate(client, fake, ["4.2"], [["4.2"], ["4.2"], ["4.2"]])
    got = client.get(f"/generations/{gen['generation_id']}").json()
    assert got["generation_id"] == gen["generation_id"] and got["overall_status"] == "stale"
    assert client.get("/generations/not-a-real-id").status_code == 404
    assert client.get("/selections/99999/generations").status_code == 404
    assert client.get("/nodes/99999/generations").status_code == 404


def test_wording_change_is_review_and_removed_section_is_flagged(env3):
    client, fake = env3
    sid, _ = generate(client, fake, ["1.1", "6.2", "4.1"], [["1.1"], ["6.2"], ["4.1"]])
    g = client.get(f"/selections/{sid}/generations").json()[0]
    assert g["checked_against_version"] == 3
    assert by_title(g) == {"Test case number 0": "review",
                           "Test case number 1": "source_removed",
                           "Test case number 2": "current"}
    assert g["overall_status"] == "source_removed"
    src = {s["number"]: s for s in g["sources"]}
    assert src["1.1"]["numbers_changed"] is False       # wording change, not a number change
    assert any("designed" in c["new"] for c in src["1.1"]["changes"])
    assert src["6.2"]["checked_number"] is None


def test_selection_without_generations_returns_empty_list(env2):
    client, fake = env2
    nid = node_id(client, "4.1", 1)
    sid = client.post("/selections", json={"name": "none", "node_ids": [nid]}).json()["id"]
    assert client.get(f"/selections/{sid}/generations").json() == []