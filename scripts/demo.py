import sys

import httpx

BASE = "http://127.0.0.1:8000"


def title(text):
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def main():
    c = httpx.Client(base_url=BASE, timeout=180)

    def call(method, url, **kwargs):
        r = c.request(method, url, **kwargs)
        if r.status_code >= 400:
            print(f"ERROR {r.status_code} on {method} {url}\n{r.text}")
            sys.exit(1)
        return r

    def node_id(number, version):
        hits = call("GET", "/search", params={"q": "", "version": version}).json()["results"]
        return next(h["id"] for h in hits if h["number"] == number)

    def show_view(view):
        print(f"  checked against v{view['checked_against_version']} -> "
              f"overall: {view['overall_status'].upper()}  {view['counts']}")
        for s in view["sources"]:
            print(f"  source {s['number']} ({s['title']}): {s['status']}")
            print(f"     {s['reason']}")
        for tc in view["test_cases"]:
            print(f"    [{tc['staleness']:^14}] {tc['title']}  "
                  f"(cites {', '.join(tc['source_sections'])})")

    try:
        existing = c.get("/versions").json()
    except httpx.ConnectError:
        print("Cannot reach the server. Start it first (see the README).")
        sys.exit(1)
    if existing:
        print("This database already has versions. Use a fresh demo database (see the README).")
        sys.exit(1)

    title("1. Ingest the v1 manual")
    r = call("POST", "/versions", json={"file": "ct200_manual.pdf"}).json()
    print(f"  version {r['number']} saved: {r['node_count']} nodes")

    title("2. Browse: top-level sections of the latest version")
    for s in call("GET", "/sections").json()["sections"]:
        print(f"  {s['number']}  {s['title']}")

    title("3. Select sections 4.1 and 4.2 of v1 (pinned to v1)")
    ids = [node_id("4.1", 1), node_id("4.2", 1)]
    sel = call("POST", "/selections", json={"name": "overpressure and errors", "node_ids": ids}).json()
    sid = sel["id"]
    print(f"  selection {sid} saved with {len(sel['items'])} pinned sections")

    title("4. Generate QA test cases with the LLM")
    gen = call("POST", f"/selections/{sid}/generate").json()
    print(f"  status: {gen['status']}, attempts: {gen['attempts']}, test cases: {len(gen['test_cases'])}")
    for tc in gen["test_cases"]:
        print(f"    - {tc['title']}  (cites {', '.join(tc['source_sections'])})")

    title("5. Staleness check while the manual is still v1")
    show_view(call("GET", f"/selections/{sid}/generations").json()[0])

    title("6. Ingest the v2 manual (v1 is kept)")
    r = call("POST", "/versions", json={"file": "ct200_manual_v2.pdf"}).json()
    print(f"  version {r['number']} saved: {r['node_count']} nodes")
    print("  versions now:", [(v["number"], v["node_count"]) for v in call("GET", "/versions").json()])

    title("7. Did section 4.2 change? (diff summary)")
    rep = call("GET", f"/nodes/{node_id('4.2', 1)}/changes").json()
    print(f"  changed across versions: {rep['changed_across_versions']}")
    for step in rep["changes"]:
        for d in step["summary"]:
            print(f"    v{step['from_version']} -> v{step['to_version']}  {d['type']}: "
                  f"'{d['old']}' -> '{d['new']}'")

    title("8. Staleness check again, now against the latest version (v2)")
    show_view(call("GET", f"/selections/{sid}/generations").json()[0])

    title("9. The same check against v1: the pinned text itself is never stale")
    show_view(call("GET", f"/selections/{sid}/generations", params={"against_version": 1}).json()[0])

    title("10. The selection still shows the exact v1 text")
    saved = call("GET", f"/selections/{sid}").json()
    for it in saved["items"]:
        print(f"  {it['number']} pinned to v{it['version']}, latest status: {it['latest_status']}")
    old_text = next(i for i in saved["items"] if i["number"] == "4.2")["body"]
    print("  4.2 text still says 'within 2 seconds':", "within 2 seconds" in old_text)

    title("11. Submit the same selection again: the saved result is reused")
    again = call("POST", f"/selections/{sid}/generate")
    print(f"  HTTP {again.status_code}, reused = {again.json()['reused']}, "
          f"same generation = {again.json()['generation_id'] == gen['generation_id']}")

    title("12. Retrieve by section id (the v2 row of 4.2)")
    views = call("GET", f"/nodes/{node_id('4.2', 2)}/generations").json()
    for v in views:
        print(f"  generation {v['generation_id'][:8]}: overall {v['overall_status'].upper()}, "
              f"{len(v['test_cases'])} test case(s) cite this section")

    print("\nDemo finished.")


if __name__ == "__main__":
    main()