"""Issue #473: E1's label says production changed when it did (ruling Q2 and
Q3, 2026-10-18).

A blocking E1 finding printed NO_PROD_CHANGE_IN_DIFF whenever its own
evidence did not reach a production change, even when the diff changed
production. It now prints PROD_CHANGE_NOT_EVIDENCE when the diff changes a
production-role file that is not inert (`roles._is_inert`), after the
suite-control and refused-opaque labels, which keep their conditions. Only
the sentence changes: severity, verdict and fingerprint are what they were.

The .gwcase fixtures carry the shapes the ruling names:
hardcoded_package_only_pos (#471's fixture of pin 1's shape, which replaced
pin 1, prod_change_not_evidence_hardcoded_pos, when #471's fix merged; A52),
prod_change_not_evidence_unchanged_caller_pos
and the test-only twin no_prod_change_unchanged_caller_pos. A JS test weakened
beside a Python-only production edit is the existing
js_test_in_expected_dir_weakened_with_prod_edit_pos, so no duplicate was added
(ruling Q4). These rows pin the edges of the condition.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

TODAY = datetime.date(2026, 10, 19)
TEST_PATH = "tests/test_billing.py"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = FileChange(TEST_PATH, "modified", TEST,
                      TEST.replace(b"assert total == 105.3", b"assert total > 0"))
# A readable production module the test does not reach: its symbol changes,
# and nothing the test calls is it or calls it.
UNRELATED = FileChange("app/util.py", "modified", b"def f():\n    return 1\n", b"def f():\n    return 2\n")
LICENSE = FileChange("LICENSE", "modified", b"MIT\n", b"MIT License\n")
# A comment edited in an existing template, as tests/test_issue419_opaque_refusal.py
# uses: an opaque change a weakened Python assertion may not take (#419).
TEMPLATE = FileChange(
    "app/templates/invoice.html", "modified",
    b"<!-- invoice summary -->\n<p>Total: {{ total }}</p>",
    b"<!-- invoice summary, two decimals -->\n<p>Total: {{ total }}</p>",
)


def _run(*changes, root_reader=None):
    ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY, root_reader=root_reader)
    return ir, [(f.rule, f.severity, f.escalators, f.deescalators) for f in findings], verdict


@pytest.mark.parametrize("inert", [
    LICENSE,
    FileChange(".gitignore", "modified", b"*.pyc\n", b"*.pyc\n.venv/\n"),
    FileChange("CITATION.cff", "modified", b"cff-version: 1.2.0\n", b"cff-version: 1.2.0\ntitle: app\n"),
], ids=["license", "gitignore", "citation"])
def test_an_inert_file_alone_keeps_the_old_wording(inert):
    # The engine records the file as a production-role change; the label
    # does not count it, as inert_doc_change_pos and stub_change_pos pin
    # for mkdocs.yml and a .pyi stub.
    ir, findings, verdict = _run(WEAKENED, inert)
    assert ir.globals.prod_files_changed == [inert.path]
    assert findings == [("ASSERT_WEAKENED", "high", ["NO_PROD_CHANGE_IN_DIFF"], [])]
    assert verdict == "block"


def test_an_inert_file_beside_a_readable_production_edit_is_a_production_change():
    _ir, findings, verdict = _run(WEAKENED, LICENSE, UNRELATED)
    assert findings == [("ASSERT_WEAKENED", "high", ["PROD_CHANGE_NOT_EVIDENCE"], [])]
    assert verdict == "block"


def test_a_production_file_whose_content_runs_the_suite_is_a_production_change():
    # Not runner-shaped, so it stays production; it names a runner, so it
    # is no opaque change (engine.py, `_mentions_test_runner`). Ruling Q2
    # names this case.
    settings = FileChange("config/settings.json", "modified",
                          b'{"runner": "pytest -q"}\n', b'{"runner": "pytest -q -x"}\n')
    ir, findings, verdict = _run(WEAKENED, settings)
    assert ir.globals.prod_opaque_change is False
    assert ir.globals.prod_files_changed == ["config/settings.json"]
    assert findings == [("ASSERT_WEAKENED", "high", ["PROD_CHANGE_NOT_EVIDENCE"], [])]
    assert verdict == "block"


def test_a_refused_opaque_change_keeps_its_label_beside_a_readable_edit():
    ir, findings, verdict = _run(WEAKENED, TEMPLATE, UNRELATED)
    assert ir.globals.prod_opaque_change is True
    assert findings == [("ASSERT_WEAKENED", "high", ["OPAQUE_PROD_CHANGE_NOT_EVIDENCE"], [])]
    assert verdict == "block"


def test_a_suite_control_beside_only_an_inert_file_keeps_d066s_test():
    # COLLECTION_CONTROL_UNEXPLAINED counts any production-role file,
    # inert ones included (D-066); #473 does not change that.
    conftest = FileChange("tests/conftest.py", "modified", b"import pytest\n",
                          b'import pytest\n\ncollect_ignore = ["test_billing.py"]\n')
    _ir, findings, verdict = _run(conftest, LICENSE, root_reader={}.get)
    assert findings == [("TEST_DISABLED", "high", ["COLLECTION_CONTROL_UNEXPLAINED"], [])]
    assert verdict == "block"
