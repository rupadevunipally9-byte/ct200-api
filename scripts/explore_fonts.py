import sys
import pymupdf

doc = pymupdf.open(sys.argv[1])
for page_no, page in enumerate(doc, start=1):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            s = line["spans"][0]
            bold = bool(s["flags"] & 16)
            print(f"p{page_no} size={s['size']:.1f} bold={bold} | {text}")