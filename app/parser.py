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