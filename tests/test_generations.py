import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.generations import get_llm, get_store
from app.ingest import ingest_pdf
from app.llm import LLMError
from app.main import app, get_db
from app.store import JsonStore


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ingest_pdf(s, "data/ct200_manual.pdf")
        ingest_pdf(s, "data/ct200_manual_v2.pdf")
    return eng


class FakeLLM:
    def __init__(self):
        self.replies = []
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture()
def env(engine, tmp_path):
    fake, store = FakeLLM(), JsonStore(tmp_path)

    def db_override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app), fake, store
    app.dependency_overrides.clear()


def make_selection(client, numbers=("4.2",), version=2, name="sel"):
    hits = client.get("/search", params={"q": "", "version": version}).json()["results"]
    ids = [h["id"] for h in hits if h["number"] in numbers]
    return client.post("/selections", json={"name": name, "node_ids": ids}).json()["id"]


def good(sections=("4.2",), n=3, expected="Device shows the error and releases the air"):
    cases = [{
        "title": f"Case {'ABCDE'[i]} for overpressure",
        "objective": "Check the safety behaviour",
        "preconditions": ["Device is on"],
        "steps": ["Start a measurement", "Raise the pressure too high"],
        "expected_result": expected,
        "priority": "high",
        "source_sections": list(sections),
    } for i in range(n)]
    return json.dumps({"test_cases": cases})


def test_happy_path_saves_one_generation(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = [good()]
    r = client.post(f"/selections/{sid}/generate")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ok" and body["attempts"] == 1 and body["reused"] is False
    assert len(body["test_cases"]) == 3
    assert body["sources"][0]["number"] == "4.2"
    assert len(store.all()) == 1


def test_malformed_reply_is_retried_with_the_error_explained(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = ["this is not json", good()]
    body = client.post(f"/selections/{sid}/generate").json()
    assert body["attempts"] == 2
    assert len(fake.calls[1]) == 4 and "rejected" in fake.calls[1][-1]["content"]


def test_all_attempts_bad_gives_error_and_saves_only_a_failed_record(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = ["not json", json.dumps({"test_cases": []}), json.dumps({"hello": 1})]
    r = client.post(f"/selections/{sid}/generate")
    assert r.status_code == 502 and len(fake.calls) == 3
    docs = store.all()
    assert len(docs) == 1 and docs[0]["status"] == "failed" and len(docs[0]["failures"]) == 3
    fake.replies = [good()]            # a failure is never cached: trying again works
    again = client.post(f"/selections/{sid}/generate")
    assert again.status_code == 201 and again.json()["reused"] is False


def test_json_wrapped_in_code_fence_is_accepted(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = ["```json\n" + good() + "\n```"]
    assert client.post(f"/selections/{sid}/generate").json()["attempts"] == 1


def test_citing_a_section_that_was_not_selected_is_rejected(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = [good(("9.9",)), good()]
    assert client.post(f"/selections/{sid}/generate").json()["attempts"] == 2


def test_same_selection_twice_reuses_and_force_makes_a_new_one(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = [good()]
    first = client.post(f"/selections/{sid}/generate").json()
    second = client.post(f"/selections/{sid}/generate")
    assert second.status_code == 200 and second.json()["reused"] is True
    assert second.json()["generation_id"] == first["generation_id"]
    assert len(fake.calls) == 1 and len(store.all()) == 1
    fake.replies = [good()]
    forced = client.post(f"/selections/{sid}/generate", params={"force": True})
    assert forced.status_code == 201
    assert forced.json()["generation_id"] != first["generation_id"]
    assert len(store.all()) == 2


def test_number_not_in_source_text_is_flagged_as_warning(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = [good(expected="Device releases the air within 9 seconds")]
    body = client.post(f"/selections/{sid}/generate").json()
    assert body["status"] == "ok"
    assert body["test_cases"][0]["unsupported_numbers"] == ["9"]


def test_ai_service_down_gives_502_and_saves_nothing(env):
    client, fake, store = env
    sid = make_selection(client)
    fake.replies = [LLMError("service is down")]
    assert client.post(f"/selections/{sid}/generate").status_code == 502
    assert store.all() == []


def test_unknown_selection_is_404(env):
    client, fake, store = env
    assert client.post("/selections/99999/generate").status_code == 404