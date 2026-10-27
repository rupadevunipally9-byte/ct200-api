import pytest
from app.parser import build_tree

V1 = "data/ct200_manual.pdf"
V2 = "data/ct200_manual_v2.pdf"


@pytest.fixture(scope="module")
def v1():
    return {n["number"]: n for n in build_tree(V1)}


@pytest.fixture(scope="module")
def v2():
    return {n["number"]: n for n in build_tree(V2)}


def test_duplicate_heading_gives_two_nodes_with_correct_parents(v1):
    assert v1["4.2"]["title"] == v1["7.1"]["title"] == "Error Codes"
    assert v1["4.2"]["parent"] == "4"
    assert v1["7.1"]["parent"] == "7"
    assert v1["4.2"]["body"] != v1["7.1"]["body"]


def test_skipped_level_attaches_to_nearest_existing_parent(v1):
    assert "2.1.1" not in v1
    assert v1["2.1.1.1"]["level"] == 4
    assert v1["2.1.1.1"]["parent"] == "2.1"


def test_out_of_order_sections_keep_correct_parent_and_text(v1):
    order = [n for n in v1 if n in ("3.3", "3.4")]
    assert order == ["3.4", "3.3"]          # 3.4 really comes first in the PDF
    assert v1["3.4"]["parent"] == v1["3.3"]["parent"] == "3"
    assert "automatically powers off" in v1["3.4"]["body"]
    assert "Normal: systolic" in v1["3.3"]["body"]


def test_numbered_list_is_not_turned_into_headings(v1):
    numbers = [n for n in v1]
    assert numbers.count("1") == 1          # only the real "1. Device Overview"
    items = [l for l in v1["3.3"]["body"].split("\n") if l[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert len(items) == 5


def test_paragraph_cut_by_page_break_is_joined(v1):
    body = v1["3.1"]["body"]
    assert "power on the device. Use the profile button" in body


def test_table_values_are_exact_in_both_versions(v1, v2):
    assert "Auto-deflates within 2 seconds, displays E3" in v1["4.2"]["body"]
    assert "Auto-deflates within 1.5 seconds, displays E3" in v2["4.2"]["body"]
    assert "| E6 |" not in v1["4.2"]["body"]
    assert "| E6 |" in v2["4.2"]["body"]


def test_only_real_changes_get_a_different_hash(v1, v2):
    changed = {n for n in v1 if n in v2 and v1[n]["hash"] != v2[n]["hash"]}
    added = set(v2) - set(v1)
    assert changed == {"2.1.1.1", "3.2", "4.2", "4.3"}
    assert added == {"5.3"}
def test_pdf_without_text_layer_is_refused_with_a_clear_message(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()                      # a blank page, like a scan with no text layer
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    with pytest.raises(ValueError, match="No text found"):
        build_tree(str(path))