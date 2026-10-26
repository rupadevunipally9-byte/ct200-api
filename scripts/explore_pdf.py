import sys
import pymupdf

path = sys.argv[1]
doc = pymupdf.open(path)

for page_no, page in enumerate(doc, start=1):
    print(f"===== PAGE {page_no} =====")
    for i, line in enumerate(page.get_text().split("\n"), start=1):
        print(f"{i:3}: {line!r}")