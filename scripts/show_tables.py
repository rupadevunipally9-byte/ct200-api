import sys
import pymupdf

doc = pymupdf.open(sys.argv[1])
for page_no, page in enumerate(doc, start=1):
    found = page.find_tables()
    print(f"page {page_no}: {len(found.tables)} table(s)")
    for t in found.tables:
        print("  bbox:", [round(x) for x in t.bbox])
        for row in t.extract():
            print("   ", row)