import sys
sys.path.insert(0, ".")
from app.parser import read_lines, find_headings

for h in find_headings(read_lines(sys.argv[1])):
    print("    " * (h["level"] - 1) + f"{h['number']}  {h['title']}  (level {h['level']}, page {h['page']})")