import json
import os
import re
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{32}$")


class JsonStore:
    """One JSON file per generation. Files are written to a temp file first,
    then renamed, so a crash never leaves a half-written record."""

    def __init__(self, root):
        self.dir = Path(root) / "generations"
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, doc):
        path = self.dir / f"{doc['generation_id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def get(self, generation_id):
        if not ID_RE.match(generation_id):
            return None
        path = self.dir / f"{generation_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def all(self):
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in self.dir.glob("*.json")]
        return sorted(docs, key=lambda d: d["created_at"])

    def find(self, selection_id=None, logical_id=None):
        out = []
        for d in self.all():
            if selection_id is not None and d["selection_id"] != selection_id:
                continue
            if logical_id is not None and logical_id not in {s["logical_id"] for s in d["sources"]}:
                continue
            out.append(d)
        return out