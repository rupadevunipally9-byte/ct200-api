import hashlib
import re
import unicodedata
import pymupdf




HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")


def clean(text):
    text = unicodedata.normalize("NFKC", text)  # fi, ff, fl letters become normal
    text = text.replace("\u2010", "-").replace("\u2011", "-")  # special hyphens
    return text.strip()


def read_lines(pdf_path):
    doc = pymupdf.open(pdf_path)
    lines = []
    for page_no, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = clean("".join(s["text"] for s in line["spans"]))
                if not text:
                    continue
                span = line["spans"][0]
                lines.append({
                    "page": page_no,
                    "text": text,
                    "bold": bool(span["flags"] & 16),
                    "size": round(span["size"], 1),
                })
    return lines


def find_headings(lines):
    headings = []
    for ln in lines:
        match = HEADING_RE.match(ln["text"])
        if ln["bold"] and match:
            number, title = match.groups()
            headings.append({
                "number": number,
                "title": title,
                "level": number.count(".") + 1,
                "page": ln["page"],
            })
    return headings
LIST_RE = re.compile(r"^\d+\.\s")


def normalize_for_hash(text):
    return " ".join(text.lower().split())


def content_hash(text):
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def join_body(body_lines):
    """Join lines into text. A new list item starts a new line;
    everything else continues the previous line (this also fixes page breaks)."""
    out = []
    for ln in body_lines:
        if not out or LIST_RE.match(ln):
            out.append(ln)
        else:
            out[-1] += " " + ln
    return "\n".join(out)


def build_tree(pdf_path):
    lines = read_lines(pdf_path)

    # the title = the first lines with the biggest font size
    biggest = max(ln["size"] for ln in lines)
    title_lines = [ln["text"] for ln in lines if ln["size"] == biggest]
    nodes = [{
        "number": "0", "title": " ".join(title_lines), "level": 0,
        "parent": None, "page": 1, "body_lines": [],
    }]
    by_number = {"0": nodes[0]}
    current = nodes[0]

    for ln in lines:
        if ln["size"] == biggest:
            continue  # skip title lines
        match = HEADING_RE.match(ln["text"])
        if ln["bold"] and match:
            number, title = match.groups()
            parts = number.split(".")
            parent = by_number["0"]
            for i in range(len(parts) - 1, 0, -1):  # try shorter numbers
                candidate = ".".join(parts[:i])
                if candidate in by_number:
                    parent = by_number[candidate]
                    break
            node = {
                "number": number, "title": title, "level": len(parts),
                "parent": parent["number"], "page": ln["page"], "body_lines": [],
            }
            nodes.append(node)
            by_number[number] = node
            current = node
        else:
            current["body_lines"].append(ln["text"])

    for n in nodes:
        n["body"] = join_body(n.pop("body_lines"))
        n["hash"] = content_hash(n["body"])
    return nodes