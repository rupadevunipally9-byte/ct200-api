import hashlib
import re
import unicodedata
import pymupdf

HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
LIST_RE = re.compile(r"^\d+\.\s")


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
                    "bbox": line["bbox"],
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


def center_in(bbox, rect, pad=1):
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return rect[0] - pad <= cx <= rect[2] + pad and rect[1] - pad <= cy <= rect[3] + pad


def contained(bbox, rect, pad=2):
    return (bbox[0] >= rect[0] - pad and bbox[2] <= rect[2] + pad
            and bbox[1] >= rect[1] - pad and bbox[3] <= rect[3] + pad)


def attach_tables(pdf_path, lines):
    """Use PyMuPDF for the table SHAPE only. Cell text comes from our clean lines.
    Raises an error if any line inside a table does not fit in a cell."""
    doc = pymupdf.open(pdf_path)
    tables = []
    for page_no, page in enumerate(doc, start=1):
        for t in page.find_tables().tables:
            inside = [ln for ln in lines
                      if ln["page"] == page_no and center_in(ln["bbox"], t.bbox)]
            used = set()
            rows = []
            for row in t.rows:
                cells = []
                for cell_bbox in row.cells:
                    if cell_bbox is None:
                        cells.append("")
                        continue
                    in_cell = [ln for ln in inside if contained(ln["bbox"], cell_bbox)]
                    in_cell.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
                    used.update(id(ln) for ln in in_cell)
                    cells.append(" ".join(l["text"] for l in in_cell))
                rows.append(cells)
            if len(used) != len(inside):
                raise ValueError(
                    f"Table on page {page_no}: {len(inside) - len(used)} line(s) "
                    f"do not fit in any cell. Table not supported, stopping.")
            table_id = len(tables)
            for ln in inside:
                ln["table_id"] = table_id
            tables.append({"page": page_no, "rows": rows})
    return tables


def normalize_for_hash(text):
    return " ".join(text.lower().split())


def content_hash(text):
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def join_body(body_lines):
    """A list item or table row starts a new line; everything else continues
    the previous line (this also fixes paragraphs cut by page breaks)."""
    out = []
    for ln in body_lines:
        starts_new = (not out or LIST_RE.match(ln) or ln.startswith("|")
                      or out[-1].startswith("|"))
        if starts_new:
            out.append(ln)
        else:
            out[-1] += " " + ln
    return "\n".join(out)


def build_tree(pdf_path):
    lines = read_lines(pdf_path)
    tables = attach_tables(pdf_path, lines)
    emitted = set()

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

        table_id = ln.get("table_id")
        if table_id is not None:
            if table_id not in emitted:  # write the whole table once
                emitted.add(table_id)
                for row in tables[table_id]["rows"]:
                    current["body_lines"].append("| " + " | ".join(row) + " |")
            continue

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