import hashlib
from pathlib import Path

from sqlalchemy import select

from app.models import Document, LogicalNode, NodeVersion, Version
from app.parser import build_tree
class AlreadyIngested(ValueError):
    pass

def norm_title(title):
    return " ".join(title.lower().split())


def match_nodes(new_nodes, prev_rows):
    """Returns {new section number: (old row, how it was matched)}."""
    matches = {}
    prev_by_key = {(p.number, norm_title(p.title)): p for p in prev_rows}
    used_prev = set()

    # Rule 1: same number AND same title
    for n in new_nodes:
        p = prev_by_key.get((n["number"], norm_title(n["title"])))
        if p:
            matches[n["number"]] = (p, "number+title")
            used_prev.add(p.id)

    # Rule 2 (backup): title is unique among the leftovers on both sides
    left_new = [n for n in new_nodes if n["number"] not in matches]
    left_prev = [p for p in prev_rows if p.id not in used_prev]
    for n in left_new:
        same_new = [x for x in left_new if norm_title(x["title"]) == norm_title(n["title"])]
        same_prev = [p for p in left_prev if norm_title(p.title) == norm_title(n["title"])]
        if len(same_new) == 1 and len(same_prev) == 1:
            matches[n["number"]] = (same_prev[0], "title-only")
    return matches


def ingest_pdf(db, pdf_path, doc_name="CT-200 Manual"):
    sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    nodes = build_tree(pdf_path)  # parse first: if this fails, nothing is saved

    doc = db.scalar(select(Document).where(Document.name == doc_name))
    if doc is None:
        doc = Document(name=doc_name)
        db.add(doc)
        db.flush()

    versions = db.scalars(
        select(Version).where(Version.document_id == doc.id).order_by(Version.number)
    ).all()
    for v in versions:
        if v.file_sha256 == sha:
            raise AlreadyIngested(f"This exact file is already ingested as version {v.number}.")
    latest = versions[-1] if versions else None

    version = Version(
        document_id=doc.id,
        number=latest.number + 1 if latest else 1,
        source_file=Path(pdf_path).name,
        file_sha256=sha,
    )
    db.add(version)
    db.flush()

    prev_rows = []
    if latest:
        prev_rows = db.scalars(
            select(NodeVersion).where(NodeVersion.version_id == latest.id)
        ).all()
    matches = match_nodes(nodes, prev_rows)

    rows = {}
    for position, n in enumerate(nodes):
        found = matches.get(n["number"])
        if found:
            prev, method = found
            logical_id = prev.logical_id
            status = "unchanged" if prev.content_hash == n["hash"] else "changed"
        else:
            logical = LogicalNode(document_id=doc.id)
            db.add(logical)
            db.flush()
            logical_id = logical.id
            method = "new"
            status = "new" if latest is None else "added"
        row = NodeVersion(
            logical_id=logical_id, version_id=version.id, number=n["number"],
            title=n["title"], level=n["level"], position=position, page=n["page"],
            body=n["body"], content_hash=n["hash"],
            change_status=status, match_method=method,
        )
        db.add(row)
        rows[n["number"]] = row
    db.flush()

    for n in nodes:  # now every row has an id, so set the parents
        if n["parent"] is not None:
            rows[n["number"]].parent_id = rows[n["parent"]].id

    db.commit()
    return version