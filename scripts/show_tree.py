import sys
sys.path.insert(0, ".")
from app.parser import build_tree

for n in build_tree(sys.argv[1]):
    print(f"{n['number']:9} parent={str(n['parent']):5} hash={n['hash'][:8]} chars={len(n['body'])}  {n['title']}")
    if n["number"] in ("2.1.1.1", "3.1", "3.3"):
        print("      BODY:", repr(n["body"]))