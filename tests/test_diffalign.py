"""Alignment tests: renames must never read as deletions (SPEC §7)."""

from greenwash.frontends.python.frontend import parse_python
from greenwash.ir.diffalign import align_file


def _align(before_src: str, after_src: str, **kwargs):
    before = parse_python(before_src.encode(), collect_tests=True)
    after = parse_python(after_src.encode(), collect_tests=True)
    return align_file("tests/test_x.py", "test", "modified", before, after, **kwargs)


def test_renamed_test_matched_by_fingerprint():
    before = (
        "def test_total():\n"
        "    items = load_items('fixtures/basic.json')\n"
        "    total = compute_invoice_total(items)\n"
        "    assert total == 105.3\n"
        "    assert total > 0\n"
    )
    after = (
        "def test_invoice_total_after_tax():\n"
        "    items = load_items('fixtures/basic.json')\n"
        "    total = compute_invoice_total(items)\n"
        "    assert total == 105.3\n"
        "    assert total > 0\n"
    )
    file_ir = _align(before, after)
    assert len(file_ir.units) == 1
    unit = file_ir.units[0]
    assert unit.match == "by_fingerprint"
    assert unit.delta is not None
    assert unit.delta.assertions_removed == []
    assert file_ir.alignment == "full"


def test_unrelated_tests_not_force_matched():
    before = "def test_a():\n    assert parse('x') == 1\n"
    after = (
        "def test_b():\n"
        "    payload = build_payload(user='alice', scope='admin')\n"
        "    response = client.post('/api/v2/session', json=payload)\n"
        "    assert response.status_code == 201\n"
    )
    file_ir = _align(before, after)
    matches = {u.match for u in file_ir.units}
    assert matches == {None}
    assert len(file_ir.units) == 2


def test_degraded_alignment_is_flagged():
    before = "\n".join(f"def test_{i}():\n    assert f({i}) == {i}\n" for i in range(3))
    after = "\n".join(f"def test_r{i}():\n    assert f({i}) == {i}\n" for i in range(3))
    file_ir = _align(before, after, max_unpaired=2)
    assert file_ir.alignment == "degraded"


def test_qualname_pairing_wins_over_similarity():
    src = "def test_a():\n    assert f() == 1\n"
    file_ir = _align(src, src)
    assert file_ir.units[0].match == "by_name"
    assert file_ir.units[0].delta.assertion_pairs[0].strength_change == 0
