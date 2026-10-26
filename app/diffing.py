import difflib
import re

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def diff_summary(old, new, limit=20):
    a, b = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changes.append({
                "type": tag,  # replace / delete / insert
                "old": " ".join(a[i1:i2]),
                "new": " ".join(b[j1:j2]),
            })
    return {
        "numbers_changed": sorted(NUM_RE.findall(old)) != sorted(NUM_RE.findall(new)),
        "summary": changes[:limit],
        "more": max(0, len(changes) - limit),
    }