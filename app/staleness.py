from collections import Counter

from pydantic import BaseModel
from sqlalchemy import select

from app.diffing import diff_summary
from app.generation import StoredTestCase
from app.models import NodeVersion
from app.schemas import DiffItem

RANK = {"current": 0, "review": 1, "stale": 2, "source_removed": 3}


class SourceCheck(BaseModel):
    number: str
    title: str
    pinned_version: int
    checked_version: int
    checked_number: str | None
    status: str
    reason: str
    numbers_changed: bool
    changes: list[DiffItem]


class CaseView(StoredTestCase):
    staleness: str
    stale_because: list[str]


class GenerationView(BaseModel):
    generation_id: str
    selection_id: int
    created_at: str
    model: str
    prompt_version: str
    attempts: int
    checked_against_version: int
    overall_status: str
    counts: dict[str, int]
    sources: list[SourceCheck]
    test_cases: list[CaseView]


def check_source(db, source, target):
    """Compare one pinned section with the same logical section in the target version."""
    base = {"number": source["number"], "title": source["title"],
            "pinned_version": source["version"], "checked_version": target.number,
            "checked_number": None, "numbers_changed": False, "changes": []}
    row = db.scalars(select(NodeVersion).where(
        NodeVersion.logical_id == source["logical_id"],
        NodeVersion.version_id == target.id)).first()
    if row is None:
        return {**base, "status": "source_removed",
                "reason": f"Section {source['number']} does not exist in version "
                          f"{target.number} (removed, or renumbered/retitled)."}
    base["checked_number"] = row.number
    if row.content_hash == source["content_hash"]:
        return {**base, "status": "current",
                "reason": "Text is identical to what the test cases were written from."}
    old = db.get(NodeVersion, source["node_version_id"])
    d = diff_summary(old.body, row.body)
    base["changes"] = d["summary"]
    base["numbers_changed"] = d["numbers_changed"]
    if d["numbers_changed"]:
        return {**base, "status": "stale",
                "reason": "A number (limit, time or count) differs. Treat the test cases "
                          "as wrong until a person re-checks them."}
    return {**base, "status": "review",
            "reason": "Wording changed but no numbers changed. A person should read "
                      "the change: it may or may not matter."}


def build_view(db, doc, target, only_logical=None):
    checks = {s["number"]: check_source(db, s, target) for s in doc["sources"]}
    wanted = None
    if only_logical is not None:
        wanted = {s["number"] for s in doc["sources"] if s["logical_id"] == only_logical}
    cases = []
    for tc in doc["test_cases"]:
        cited = [n for n in tc["source_sections"] if n in checks] or list(checks)
        if wanted is not None and not (set(cited) & wanted):
            continue
        worst = max((checks[n]["status"] for n in cited), key=RANK.get)
        because = [n for n in cited if checks[n]["status"] != "current"]
        cases.append(CaseView(**tc, staleness=worst, stale_because=because))
    statuses = [c.staleness for c in cases]
    counts = Counter(statuses)
    return GenerationView(
        generation_id=doc["generation_id"], selection_id=doc["selection_id"],
        created_at=doc["created_at"], model=doc["model"],
        prompt_version=doc["prompt_version"], attempts=doc["attempts"],
        checked_against_version=target.number,
        overall_status=max(statuses, key=RANK.get) if statuses else "current",
        counts={k: counts.get(k, 0) for k in RANK},
        sources=[SourceCheck(**c) for c in checks.values()],
        test_cases=cases)