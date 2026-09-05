"""Expected-value provenance family matrix (issues #92 and #89).

The detector must follow the *expectation side* of a reachable assertion to
the value that supplies it.  It must not decide that a name such as
``expected`` is special: every positive has a paired direction control where
the same carrier feeds the subject instead.

``direct`` means the assertion is written in the collected test.  ``inherited``
means it lives in a same-file helper the test invokes.  For ``helper_actual``
the first hop is necessarily inherited; its second scope is a forwarded
two-helper call.  Cross-file helper and conftest-fixture boundaries are pinned
separately below.

Named residuals are pinned rather than hidden by the green matrix: external
JSON/YAML carriers, constants imported from another Python module, cross-file
helper defaults, variadic helper oracles, dynamic ``indirect=`` expressions,
and parallel expected swaps/padding that preserve an add/delete-compatible
expected-value multiset have no deterministic direction proof in IR v1 yet.
A genuinely unresolved fixture public name is different: changing its
definition, or following it past a possible override, would otherwise fail
open or create a false positive, so those ambiguities raise an engine error.
Statically ordered module string aliases (including constant chains and
proven execution-time walruses) are resolved afresh on each side; an unchanged
irrelevant alias remains inert.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.cli import _file_contains_any_fixed
from checkwash.engine import EngineError, FileChange, analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.gitio import GitError, grep_head_paths
from checkwash.pyenv import known_baseline

TODAY = datetime.date(2026, 1, 1)
RULE = "EXPECTATION_DEFINITION_CHANGED"


def _run(
    before: str,
    after: str,
    *,
    path: str = "tests/test_answer.py",
    extra_changes: list[FileChange] | None = None,
    head: dict[str, str] | None = None,
):
    changes = [
        FileChange(
            path=path,
            status="modified",
            before=before.encode("utf-8"),
            after=after.encode("utf-8"),
        ),
        *(extra_changes or []),
    ]
    head_bytes = {p: text.encode("utf-8") for p, text in (head or {}).items()}

    def search(needles: list[str]) -> list[str]:
        encoded = [needle.encode("utf-8") for needle in needles]
        return [
            candidate
            for candidate, data in sorted(head_bytes.items())
            if any(needle in data for needle in encoded)
        ]

    _ir, findings, verdict = analyze(
        changes,
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=known_baseline(),
        head_reader=head_bytes.get if head_bytes else None,
        head_searcher=search if head_bytes else None,
    )
    return verdict, [finding for finding in findings if not finding.allowlisted]


def _local(scope: str, value: int) -> str:
    helper = (
        "\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        if scope == "inherited"
        else ""
    )
    assertion = (
        "    assert_answer(answer(), want)\n"
        if scope == "inherited"
        else "    assert answer() == want\n"
    )
    return (
        "from app import answer\n"
        f"{helper}\n\n"
        "def test_answer():\n"
        f"    want = {value}\n"
        f"{assertion}"
    )


def _parametrize(scope: str, value: int) -> str:
    helper = (
        "\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        if scope == "inherited"
        else ""
    )
    assertion = (
        "    assert_answer(answer(), want)\n"
        if scope == "inherited"
        else "    assert answer() == want\n"
    )
    return (
        "import pytest\n\n"
        "from app import answer\n"
        f"{helper}\n\n"
        f"@pytest.mark.parametrize('want', [{value}])\n"
        "def test_answer(want):\n"
        f"{assertion}"
    )


def _fixture(scope: str, value: int) -> str:
    helper = (
        "\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        if scope == "inherited"
        else ""
    )
    assertion = (
        "    assert_answer(answer(), answer_value)\n"
        if scope == "inherited"
        else "    assert answer() == answer_value\n"
    )
    return (
        "import pytest\n\n"
        "from app import answer\n"
        f"{helper}\n\n"
        "@pytest.fixture\n"
        "def answer_value():\n"
        f"    return {value}\n\n\n"
        "def test_answer(answer_value):\n"
        f"{assertion}"
    )


def _module_table(scope: str, value: int) -> str:
    helper = (
        "\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        if scope == "inherited"
        else ""
    )
    assertion = (
        "        assert_answer(answer(raw), want)\n"
        if scope == "inherited"
        else "        assert answer(raw) == want\n"
    )
    return (
        "from app import answer\n\n"
        f"CASES = [(1, {value}), (2, 8)]\n"
        f"{helper}\n\n"
        "def test_answer():\n"
        "    for raw, want in CASES:\n"
        f"{assertion}"
    )


def _class_attr(scope: str, value: int) -> str:
    helper = (
        "\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        if scope == "inherited"
        else ""
    )
    assertion = (
        "        assert_answer(answer(), self.want)\n"
        if scope == "inherited"
        else "        assert answer() == self.want\n"
    )
    return (
        "from app import answer\n"
        f"{helper}\n\n"
        "class TestAnswer:\n"
        f"    want = {value}\n\n"
        "    def test_answer(self):\n"
        f"{assertion}"
    )


def _helper_actual(scope: str, value: int) -> str:
    relay = (
        "\n\ndef relay(got, forwarded):\n"
        "    assert_answer(got, forwarded)\n"
        if scope == "inherited"
        else ""
    )
    callee = "relay" if scope == "inherited" else "assert_answer"
    return (
        "from app import answer\n\n\n"
        "def assert_answer(got, oracle):\n"
        "    assert got == oracle\n"
        f"{relay}\n\n"
        "def test_answer():\n"
        f"    {callee}(answer(), {value})\n"
    )


BUILDERS = {
    "helper_actual": _helper_actual,
    "module_table": _module_table,
    "parametrize": _parametrize,
    "fixture": _fixture,
    "local": _local,
    "class_attr": _class_attr,
}

POSITIVE_CELLS = [
    (origin, scope)
    for origin in BUILDERS
    for scope in ("direct", "inherited")
]


@pytest.mark.parametrize("origin,scope", POSITIVE_CELLS, ids=lambda value: value)
def test_positive_origin_scope_cell(origin: str, scope: str):
    before = BUILDERS[origin](scope, 5)
    after = BUILDERS[origin](scope, 4)
    verdict, findings = _run(before, after)
    hits = [finding for finding in findings if finding.rule == RULE]
    assert hits, (
        f"{origin} x {scope}: changed expectation origin was silent; "
        f"verdict={verdict}, findings={[finding.rule for finding in findings]}"
    )
    assert hits[0].severity == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in hits[0].escalators
    assert verdict == "block"


def _negative_local() -> tuple[str, str]:
    return (
        "from app import answer\n\n\ndef test_answer():\n"
        "    raw = 5\n    assert answer(raw) == 9\n",
        "from app import answer\n\n\ndef test_answer():\n"
        "    raw = 4\n    assert answer(raw) == 9\n",
    )


def _negative_parametrize() -> tuple[str, str]:
    template = (
        "import pytest\n\nfrom app import answer\n\n\n"
        "@pytest.mark.parametrize('raw,want', [({raw}, 9)])\n"
        "def test_answer(raw, want):\n    assert answer(raw) == want\n"
    )
    return template.format(raw=5), template.format(raw=4)


def _negative_fixture() -> tuple[str, str]:
    template = (
        "import pytest\n\nfrom app import answer\n\n\n"
        "@pytest.fixture\ndef raw():\n    return {raw}\n\n\n"
        "def test_answer(raw):\n    assert answer(raw) == 9\n"
    )
    return template.format(raw=5), template.format(raw=4)


def _negative_module_table() -> tuple[str, str]:
    template = (
        "from app import answer\n\nCASES = [({raw}, 9)]\n\n\n"
        "def test_answer():\n"
        "    for raw, want in CASES:\n"
        "        assert answer(raw) == want\n"
    )
    return template.format(raw=5), template.format(raw=4)


def _negative_class_attr() -> tuple[str, str]:
    template = (
        "from app import answer\n\n\nclass TestAnswer:\n"
        "    raw = {raw}\n\n"
        "    def test_answer(self):\n"
        "        assert answer(self.raw) == 9\n"
    )
    return template.format(raw=5), template.format(raw=4)


def _negative_helper_actual() -> tuple[str, str]:
    template = (
        "from app import answer\n\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n\n\n"
        "def test_answer():\n"
        "    assert_answer(answer({raw}), 9)\n"
    )
    return template.format(raw=5), template.format(raw=4)


NEGATIVE_CELLS = {
    "helper_actual": _negative_helper_actual,
    "module_table": _negative_module_table,
    "parametrize": _negative_parametrize,
    "fixture": _negative_fixture,
    "local": _negative_local,
    "class_attr": _negative_class_attr,
}


@pytest.mark.parametrize("origin", NEGATIVE_CELLS, ids=lambda value: value)
def test_subject_side_direction_cell(origin: str):
    verdict, findings = _run(*NEGATIVE_CELLS[origin]())
    hits = [finding for finding in findings if finding.rule == RULE]
    assert not hits, f"{origin}: subject carrier was mistaken for expectation provenance"
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_cross_file_helper_actual_is_followed_by_parameter_position():
    helper = "def assert_answer(got, oracle):\n    assert got == oracle\n"
    before = (
        "from .assertions import assert_answer\nfrom app import answer\n\n\n"
        "def test_answer():\n    assert_answer(answer(), 5)\n"
    )
    after = before.replace("answer(), 5", "answer(), 4")
    verdict, findings = _run(
        before,
        after,
        head={"tests/assertions.py": helper},
    )
    hits = [finding for finding in findings if finding.rule == RULE]
    assert hits, (verdict, [finding.rule for finding in findings])
    assert hits[0].severity == "high"
    assert verdict == "block"


def test_cross_file_helper_subject_actual_is_not_an_expectation():
    helper = "def assert_answer(got, oracle):\n    assert got == oracle\n"
    before = (
        "from .assertions import assert_answer\nfrom app import answer\n\n\n"
        "def test_answer():\n    assert_answer(answer(5), 9)\n"
    )
    after = before.replace("answer(5)", "answer(4)")
    verdict, findings = _run(
        before,
        after,
        head={"tests/assertions.py": helper},
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_pytest_approx_module_bound_is_expectation_origin():
    before = (
        "import pytest\nfrom app import answer\n\nBOUND = 5\n\n"
        "def test_answer():\n    assert answer() == pytest.approx(BOUND)\n"
    )
    after = before.replace("BOUND = 5", "BOUND = 4")
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_pytest_approx_module_subject_input_is_direction_control():
    before = (
        "import pytest\nfrom app import answer\n\nRAW = 5\nBOUND = 9\n\n"
        "def test_answer():\n    assert answer(RAW) == pytest.approx(BOUND)\n"
    )
    after = before.replace("RAW = 5", "RAW = 4")
    verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_cross_file_fixture_changed_at_definition_reaches_unchanged_consumer():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    hits = [finding for finding in findings if finding.rule == RULE]
    assert hits, (verdict, [finding.rule for finding in findings])
    assert hits[0].severity == "high"
    assert verdict == "block"


def test_resolved_unrelated_fixture_alias_does_not_hide_parent_fixture():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "import pytest\nfrom app import answer\n\nPUBLIC_NAME = 'unrelated'\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _unrelated():\n    return 13\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_cross_file_fixture_used_only_by_subject_is_direction_control():
    before = "import pytest\n\n@pytest.fixture\ndef raw():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(raw):\n"
        "    assert answer(raw) == 9\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_cross_file_fixture_change_is_silent_when_no_consumer_requests_it():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer():\n"
        "    assert answer() == 5\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_nearer_conftest_fixture_override_wins():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    nearer = (
        "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 13\n"
    )
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={
            "tests/unit/conftest.py": nearer,
            "tests/unit/test_answer.py": consumer,
        },
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def _fixture_decoys(count: int) -> dict[str, str]:
    return {
        f"tests/test_fixture_decoy_{index:02d}.py": (
            f"answer_value_label = 'answer_value {index}'\n\n"
            f"def test_decoy_{index}():\n    assert True\n"
        )
        for index in range(count)
    }


def test_cross_file_fixture_consumer_after_more_than_read_cap_decoys_is_found():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_zz_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    head = _fixture_decoys(18)
    head["tests/test_zz_answer.py"] = consumer
    verdict, findings = _run(
        before, after, path="tests/conftest.py", head=head
    )
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_cross_file_fixture_more_than_read_cap_decoys_only_stay_silent():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head=_fixture_decoys(18),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_searched_fixture_consumer_read_failure_is_engine_error():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    change = FileChange(
        path="tests/conftest.py",
        status="modified",
        before=before.encode(),
        after=after.encode(),
    )
    with pytest.raises(EngineError, match="could not be read"):
        analyze(
            [change],
            Config(),
            Contract(),
            [],
            TODAY,
            known_modules=known_baseline(),
            head_reader=lambda _path: None,
            head_searcher=lambda _needles: ["tests/test_answer.py"],
        )


def test_claimed_nearer_conftest_read_failure_is_engine_error():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    ).encode()
    change = FileChange(
        path="tests/conftest.py",
        status="modified",
        before=before.encode(),
        after=after.encode(),
    )

    def reader(path: str):
        return consumer if path == "tests/unit/test_answer.py" else None

    with pytest.raises(EngineError, match="ancestor conftest"):
        analyze(
            [change],
            Config(),
            Contract(),
            [],
            TODAY,
            known_modules=known_baseline(),
            head_reader=reader,
            head_searcher=lambda _needles: [
                "tests/unit/conftest.py",
                "tests/unit/test_answer.py",
            ],
        )


def test_fixture_search_scans_past_one_megabyte_with_bounded_memory(tmp_path):
    path = tmp_path / "test_late_fixture.py"
    # Start the needle five bytes before a 64 KiB boundary after 1 MiB: this
    # pins both late-file scanning and the max-needle overlap.
    path.write_bytes(b"x" * (64 * 1024 * 17 - 5) + b"answer_value")
    assert _file_contains_any_fixed(str(path), [b"answer_value"])


def test_fixture_search_read_error_is_fail_closed_with_path(tmp_path):
    path = tmp_path / "unreadable.py"
    with pytest.raises(EngineError, match="could not search Python file") as error:
        _file_contains_any_fixed(str(path), [b"answer_value"])
    assert str(path) in str(error.value)


def test_claimed_ancestor_conftest_absence_is_memoized_once():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_one(answer_value):\n"
        "    assert answer() == answer_value\n\n\n"
        "def test_two(answer_value):\n"
        "    assert answer() == answer_value\n"
    ).encode()
    nearer_decoy = b"ANSWER_VALUE_DOC = 'answer_value'\n"
    reads: dict[str, int] = {}

    def reader(path: str):
        reads[path] = reads.get(path, 0) + 1
        return {
            "tests/unit/test_answer.py": consumer,
            "tests/unit/conftest.py": nearer_decoy,
        }.get(path)

    analyze(
        [
            FileChange(
                path="tests/conftest.py",
                status="modified",
                before=before.encode(),
                after=after.encode(),
            )
        ],
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=known_baseline(),
        head_reader=reader,
        head_searcher=lambda _needles: [
            "tests/unit/conftest.py",
            "tests/unit/test_answer.py",
        ],
    )
    assert reads["tests/unit/conftest.py"] == 1


def test_issue_55_pure_helper_call_insertion_is_not_a_value_edit():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, want):\n"
        "    assert got == want\n\n\n"
        "def test_answer():\n"
        "    assert_answer(answer(1), 5)\n"
        "    assert_answer(answer(3), 7)\n"
    )
    after = before.replace(
        "    assert_answer(answer(3), 7)\n",
        "    assert_answer(answer(2), 6)\n    assert_answer(answer(3), 7)\n",
    )
    verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_row_92_faithful_helper_extraction_is_not_a_value_edit():
    before = (
        "from app import answer\n\n\ndef test_answer():\n"
        "    assert answer() == 5\n"
    )
    after = (
        "from app import answer\n\n\ndef assert_answer(got, want):\n"
        "    assert got == want\n\n\n"
        "def test_answer():\n"
        "    assert_answer(answer(), 5)\n"
    )
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


def _parallel_source(origin: str, rows: list[tuple[int, int]]) -> str:
    values = ", ".join(f"({raw}, {oracle})" for raw, oracle in rows)
    if origin == "table":
        carrier = f"CASES = [{values}]\n\n\n"
        decorator = ""
        params = ""
        body = "    for raw, oracle in CASES:\n        assert answer(raw) == oracle\n"
    else:
        carrier = "import pytest\n\n"
        decorator = f"@pytest.mark.parametrize('raw,oracle', [{values}])\n"
        params = "raw, oracle"
        body = "    assert answer(raw) == oracle\n"
    return (
        f"{carrier}from app import answer\n\n\n{decorator}"
        f"def test_answer({params}):\n{body}"
    )


def _single_composite_parallel_source(
    origin: str,
    value: str,
    *,
    expectation: bool,
) -> str:
    assertion = "answer() == want" if expectation else "answer(want) == 9"
    if origin == "module_table":
        return (
            "from app import answer\n\n"
            f"CASES = [{value}]\n\n\n"
            "def test_answer():\n"
            "    for want in CASES:\n"
            f"        assert {assertion}\n"
        )
    return (
        "import pytest\n\nfrom app import answer\n\n\n"
        f"@pytest.mark.parametrize('want', [{value}])\n"
        "def test_answer(want):\n"
        f"    assert {assertion}\n"
    )


@pytest.mark.parametrize("origin", ["parametrize", "module_table"])
@pytest.mark.parametrize(
    "before_value,after_value",
    [("(1, 2)", "(1, 3)"), ("[1, 2]", "[1, 3]")],
    ids=["tuple", "list"],
)
def test_single_composite_parallel_expectation_edit_hits(
    origin: str,
    before_value: str,
    after_value: str,
):
    verdict, findings = _run(
        _single_composite_parallel_source(origin, before_value, expectation=True),
        _single_composite_parallel_source(origin, after_value, expectation=True),
    )
    hits = [finding for finding in findings if finding.rule == RULE]
    assert hits, (origin, before_value, verdict, [finding.rule for finding in findings])
    assert hits[0].severity == "high"
    assert verdict == "block"


@pytest.mark.parametrize("origin", ["parametrize", "module_table"])
@pytest.mark.parametrize(
    "before_value,after_value",
    [("(1, 2)", "(1, 3)"), ("[1, 2]", "[1, 3]")],
    ids=["tuple", "list"],
)
def test_single_composite_parallel_subject_edit_is_direction_control(
    origin: str,
    before_value: str,
    after_value: str,
):
    verdict, findings = _run(
        _single_composite_parallel_source(origin, before_value, expectation=False),
        _single_composite_parallel_source(origin, after_value, expectation=False),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (origin, before_value, [finding.rule for finding in findings])


def _one_name_parallel_source(
    shape: str,
    value: str,
    *,
    expectation: bool,
    unpack_container: str = "tuple",
) -> str:
    assertion = "answer() == want" if expectation else "answer(want) == 9"
    if shape == "module_unpack":
        row = f"({value},)" if unpack_container == "tuple" else f"[{value}]"
        return (
            "from app import answer\n\n"
            f"CASES = [{row}]\n\n\n"
            "def test_answer():\n"
            "    for (want,) in CASES:\n"
            f"        assert {assertion}\n"
        )
    if shape == "parametrize_names_list":
        row = f"({value},)" if unpack_container == "tuple" else f"[{value}]"
        decorator = f"@pytest.mark.parametrize(['want'], [{row}])\n"
    else:
        decorator = (
            "@pytest.mark.parametrize("
            f"'want', [pytest.param({value}, marks=pytest.mark.composite, id='row')])\n"
        )
    return (
        "import pytest\n\nfrom app import answer\n\n\n"
        f"{decorator}"
        "def test_answer(want):\n"
        f"    assert {assertion}\n"
    )


@pytest.mark.parametrize(
    "shape,before_value,after_value",
    [
        ("module_unpack", "5", "4"),
        ("parametrize_names_list", "5", "4"),
        ("pytest_param_composite", "(1, 2)", "(1, 3)"),
    ],
    ids=["module-unpack", "parametrize-names-list", "pytest-param-composite"],
)
def test_one_name_parallel_shape_expectation_edit_hits(
    shape: str,
    before_value: str,
    after_value: str,
):
    verdict, findings = _run(
        _one_name_parallel_source(shape, before_value, expectation=True),
        _one_name_parallel_source(shape, after_value, expectation=True),
    )
    hits = [finding for finding in findings if finding.rule == RULE]
    assert hits, (shape, before_value, verdict, [finding.rule for finding in findings])
    assert hits[0].severity == "high"
    assert verdict == "block"


@pytest.mark.parametrize(
    "shape,before_value,after_value",
    [
        ("module_unpack", "5", "4"),
        ("parametrize_names_list", "5", "4"),
        ("pytest_param_composite", "(1, 2)", "(1, 3)"),
    ],
    ids=["module-unpack", "parametrize-names-list", "pytest-param-composite"],
)
def test_one_name_parallel_shape_subject_edit_is_direction_control(
    shape: str,
    before_value: str,
    after_value: str,
):
    verdict, findings = _run(
        _one_name_parallel_source(shape, before_value, expectation=False),
        _one_name_parallel_source(shape, after_value, expectation=False),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (shape, before_value, [finding.rule for finding in findings])


@pytest.mark.parametrize(
    "shape",
    ["module_unpack", "parametrize_names_list"],
    ids=["module-unpack", "parametrize-names-list"],
)
def test_one_name_unpack_container_refactor_is_silent(shape: str):
    verdict, findings = _run(
        _one_name_parallel_source(shape, "5", expectation=True),
        _one_name_parallel_source(
            shape,
            "5",
            expectation=True,
            unpack_container="list",
        ),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (shape, [finding.rule for finding in findings])


def test_pytest_param_same_value_metadata_edit_is_silent():
    template = (
        "import pytest\n\nfrom app import answer\n\n\n"
        "@pytest.mark.parametrize('want', [{row}])\n"
        "def test_answer(want):\n"
        "    assert answer() == want\n"
    )
    before = template.format(row="pytest.param((1, 2), id='old')")
    after = template.format(
        row="pytest.param((1, 2), marks=pytest.mark.composite, id='new')"
    )
    verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", [finding.rule for finding in findings]


def _trailing_comma_parametrize_source(value: str, *, expectation: bool) -> str:
    assertion = "answer() == want" if expectation else "answer(want) == 9"
    return (
        "import pytest\n\nfrom app import answer\n\n\n"
        f"@pytest.mark.parametrize('want,', [({value},)])\n"
        "def test_answer(want):\n"
        f"    assert {assertion}\n"
    )


def test_parametrize_trailing_comma_representation_rewrite_is_silent():
    before = _trailing_comma_parametrize_source("(1, 2)", expectation=True)
    parsed = parse_python(before.encode(), collect_tests=True)
    assert parsed.units[0].side.params == ()
    verdict, findings = _run(
        before,
        _single_composite_parallel_source(
            "parametrize", "(1, 2)", expectation=True
        ),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", [finding.rule for finding in findings]


def test_parametrize_trailing_comma_expectation_edit_is_silent_residual():
    # Supported pytest versions disagree on this row's runtime shape. Treating
    # either layer as the oracle would create a version-dependent false block.
    verdict, findings = _run(
        _trailing_comma_parametrize_source("(1, 2)", expectation=True),
        _trailing_comma_parametrize_source("(1, 3)", expectation=True),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", [finding.rule for finding in findings]


def test_parametrize_trailing_comma_subject_edit_is_direction_control():
    verdict, findings = _run(
        _trailing_comma_parametrize_source("(1, 2)", expectation=False),
        _trailing_comma_parametrize_source("(1, 3)", expectation=False),
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", [finding.rule for finding in findings]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
@pytest.mark.parametrize("edit", ["reorder", "add", "duplicate"])
def test_parallel_row_only_edits_are_silent(origin: str, edit: str):
    before_rows = [(1, 5), (2, 8), (1, 5)]
    after_rows = {
        "reorder": [(1, 5), (1, 5), (2, 8)],
        "add": [(1, 5), (2, 8), (1, 5), (3, 13)],
        "duplicate": [(1, 5), (2, 8), (1, 5), (1, 5)],
    }[edit]
    _verdict, findings = _run(
        _parallel_source(origin, before_rows),
        _parallel_source(origin, after_rows),
    )
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_expected_edit_plus_padding_is_ambiguous_and_silent(origin: str):
    # This has the same expected-value projection as adding an honest row.
    # Subject-derived row identity cannot safely disambiguate the two.
    before = _parallel_source(origin, [(1, 5), (2, 8)])
    after = _parallel_source(origin, [(1, 4), (2, 8), (3, 5)])
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_pure_row_deletion_stays_out_of_value_rule(origin: str):
    before = _parallel_source(origin, [(1, 5), (2, 8)])
    after = _parallel_source(origin, [(1, 5)])
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_unrelated_deletion_does_not_pardon_expected_edit(origin: str):
    before = _parallel_source(origin, [(1, 5), (2, 8), (3, 13)])
    after = _parallel_source(origin, [(1, 4), (2, 8)])
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_equal_expected_multiset_is_ambiguous_and_silent(origin: str):
    # This row set is also produced by swapping only the two subject cells;
    # there is no stable row identity that proves which column moved.
    before = _parallel_source(origin, [(1, 5), (2, 8)])
    after = _parallel_source(origin, [(1, 8), (2, 5)])
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_subject_values_cross_swapped_are_silent(origin: str):
    # The expected-value sequence and multiset are unchanged. Row identity is
    # derived from the subject columns, so using it alone mistakes this pure
    # subject edit for two oracle substitutions.
    before = _parallel_source(origin, [(1, 5), (2, 8)])
    after = _parallel_source(origin, [(2, 5), (1, 8)])
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("origin", ["table", "parametrize"])
def test_parallel_duplicate_identity_equal_length_rewrite_hits(origin: str):
    # One duplicate disappears, the surviving twin is rewritten, and an
    # unrelated row is duplicated to preserve total cardinality.
    before = _parallel_source(origin, [(1, 5), (1, 5), (2, 8)])
    after = _parallel_source(origin, [(1, 4), (2, 8), (2, 8)])
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def _same_subject_helper(values: list[int]) -> str:
    calls = "".join(
        f"    assert_answer(answer(1), {value})\n" for value in values
    )
    return (
        "from app import answer\n\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n\n\ndef test_answer():\n"
        f"{calls}"
    )


@pytest.mark.parametrize(
    "before_values,after_values",
    [
        ([5, 7], [7, 5]),
        ([5, 7], [5, 6, 7]),
        ([5, 7], [5, 5, 7]),
    ],
    ids=["reorder", "insert", "duplicate"],
)
def test_same_subject_helper_call_multiset_pairs_semantically(
    before_values: list[int], after_values: list[int]
):
    _verdict, findings = _run(
        _same_subject_helper(before_values),
        _same_subject_helper(after_values),
    )
    assert not [finding for finding in findings if finding.rule == RULE]


def test_pytest_default_argument_is_not_a_fixture_request():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value=5):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


@pytest.mark.parametrize(
    "decorator,signature",
    [
        (
            "@pytest.mark.parametrize('answer_value', [99], indirect=True)",
            "answer_value",
        ),
        (
            "@pytest.mark.parametrize('raw,answer_value', [(1, 99)], "
            "indirect=['answer_value'])",
            "raw, answer_value",
        ),
    ],
    ids=["bool", "name-list"],
)
def test_parametrize_indirect_still_resolves_fixture_origin(
    decorator: str, signature: str
):
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "import pytest\nfrom app import answer\n\n\n"
        f"{decorator}\n"
        f"def test_answer({signature}):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_parametrize_indirect_subject_is_direction_control():
    before = "import pytest\n\n@pytest.fixture\ndef raw():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "import pytest\nfrom app import answer\n\n\n"
        "@pytest.mark.parametrize('raw', [99], indirect=True)\n"
        "def test_answer(raw):\n"
        "    assert answer(raw) == 9\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_fixture_public_name_alias_is_resolved():
    before = (
        "import pytest\n\n@pytest.fixture(name='answer_value')\n"
        "def _answer_value():\n    return 5\n"
    )
    after = before.replace("return 5", "return 4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_nearer_fixture_public_name_alias_overrides_parent():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    nearer = (
        "import pytest\n\n@pytest.fixture(name='answer_value')\n"
        "def _local_value():\n    return 13\n"
    )
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={
            "tests/unit/conftest.py": nearer,
            "tests/unit/test_answer.py": consumer,
        },
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_unary_not_keeps_class_attribute_provenance():
    before = (
        "from app import answer\n\n\nclass TestAnswer:\n"
        "    bound = 5\n\n"
        "    def test_answer(self):\n"
        "        assert not answer() == self.bound\n"
    )
    after = before.replace("bound = 5", "bound = 4")
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_git_grep_true_error_is_not_a_no_match(monkeypatch):
    monkeypatch.setattr(
        "checkwash.gitio.git.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=128, stdout=b"", stderr=b"fatal: broken index"
        ),
    )
    with pytest.raises(GitError, match="broken index"):
        grep_head_paths("repo", "HEAD", ["answer_value"])


def test_git_grep_exit_one_is_a_no_match(monkeypatch):
    monkeypatch.setattr(
        "checkwash.gitio.git.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b""
        ),
    )
    assert grep_head_paths("repo", "HEAD", ["answer_value"]) == []


def test_searched_fixture_consumer_parse_failure_is_engine_error():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    with pytest.raises(EngineError, match="could not be parsed"):
        analyze(
            [
                FileChange(
                    path="tests/conftest.py",
                    status="modified",
                    before=before.encode(),
                    after=after.encode(),
                )
            ],
            Config(),
            Contract(),
            [],
            TODAY,
            known_modules=known_baseline(),
            head_reader=lambda _path: b"def test_answer(:\n",
            head_searcher=lambda _needles: ["tests/test_answer.py"],
        )


def test_helper_positional_to_keyword_is_faithful_rewrite():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n\n\ndef test_answer():\n"
        "    assert_answer(answer(), 5)\n"
    )
    after = before.replace(
        "assert_answer(answer(), 5)",
        "assert_answer(got=answer(), oracle=5)",
    )
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


def test_same_file_helper_default_is_a_value_origin():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, oracle=5):\n"
        "    assert got == oracle\n\n\ndef test_answer():\n"
        "    assert_answer(answer())\n"
    )
    after = before.replace("oracle=5", "oracle=4")
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_named_residual_cross_file_helper_default_is_explicit():
    consumer = (
        "from .assertions import assert_answer\nfrom app import answer\n\n\n"
        "def test_answer():\n    assert_answer(answer())\n"
    )
    helper_before = "def assert_answer(got, oracle=5):\n    assert got == oracle\n"
    helper_after = helper_before.replace("oracle=5", "oracle=4")
    _verdict, findings = _run(
        consumer,
        consumer,
        extra_changes=[
            FileChange(
                path="tests/assertions.py",
                status="modified",
                before=helper_before.encode(),
                after=helper_after.encode(),
            )
        ],
    )
    assert not [finding for finding in findings if finding.rule == RULE]


def test_named_residual_varargs_helper_oracle_is_explicit():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, *oracles):\n"
        "    assert got == oracles[0]\n\n\ndef test_answer():\n"
        "    assert_answer(answer(), 5)\n"
    )
    after = before.replace("answer(), 5", "answer(), 4")
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


def test_named_residual_kwargs_helper_oracle_is_explicit():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, **oracles):\n"
        "    assert got == oracles['oracle']\n\n\ndef test_answer():\n"
        "    assert_answer(answer(), oracle=5)\n"
    )
    after = before.replace("oracle=5", "oracle=4")
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


def test_named_residual_dynamic_indirect_is_explicit():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "import pytest\nfrom app import answer\n\nINDIRECT = True\n\n"
        "@pytest.mark.parametrize('answer_value', [99], indirect=INDIRECT)\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    _verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]


def test_constant_fixture_public_name_override_wins():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    nearer = (
        "import pytest\n\nPUBLIC_NAME = 'answer_value'\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _local_value():\n    return 13\n"
    )
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    head = {
        "tests/unit/conftest.py": nearer,
        "tests/unit/test_answer.py": consumer,
    }
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head=head,
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_constant_fixture_alias_chain_resolves_nearer_override():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    nearer = (
        "import pytest\n\nALIAS = 'answer_value'\nPUBLIC_NAME = ALIAS\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _local_value():\n    return 13\n"
    )
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={
            "tests/unit/conftest.py": nearer,
            "tests/unit/test_answer.py": consumer,
        },
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


@pytest.mark.parametrize(
    "module_effect",
    [
        "[(PUBLIC_NAME := 'answer_value') for _ in (0,)]",
        "def install_alias(marker=(PUBLIC_NAME := 'answer_value')):\n    pass",
    ],
    ids=["comprehension-walrus", "definition-default-walrus"],
)
def test_module_execution_walrus_fixture_alias_overrides_parent(
    module_effect: str,
):
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    nearer = (
        "import pytest\n\nPUBLIC_NAME = 'wrong'\n"
        f"{module_effect}\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _local_value():\n    return 13\n"
    )
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    verdict, findings = _run(
        before,
        after,
        path="tests/conftest.py",
        head={
            "tests/unit/conftest.py": nearer,
            "tests/unit/test_answer.py": consumer,
        },
    )
    assert not [finding for finding in findings if finding.rule == RULE]
    assert verdict == "pass", (verdict, [finding.rule for finding in findings])


def test_ambiguous_fixture_alias_reassignment_fails_closed():
    before = "import pytest\n\n@pytest.fixture\ndef answer_value():\n    return 5\n"
    after = before.replace("return 5", "return 4")
    consumer = (
        "import pytest\nfrom app import answer\n\n"
        "PUBLIC_NAME = 'unrelated'\nPUBLIC_NAME = choose_name()\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _local_value():\n    return 13\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    with pytest.raises(EngineError, match="dynamically named fixture"):
        _run(
            before,
            after,
            path="tests/conftest.py",
            head={"tests/test_answer.py": consumer},
        )


def test_fixture_alias_chain_value_is_recomputed_per_parse():
    source = (
        "import pytest\n\nALIAS = {value!r}\nPUBLIC_NAME = ALIAS\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _value():\n    return 13\n"
    )
    before = parse_python(
        source.format(value="answer_value").encode(), collect_tests=True
    )
    after = parse_python(
        source.format(value="unrelated").encode(), collect_tests=True
    )
    assert before.fixture_defs == {"answer_value": "13"}
    assert after.fixture_defs == {"unrelated": "13"}
    assert not before.dynamic_fixture_aliases
    assert not after.dynamic_fixture_aliases


def test_changed_dynamic_fixture_public_name_fails_closed():
    before = (
        "import pytest\n\nPUBLIC_NAME = choose_name()\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _answer_value():\n    return 5\n"
    )
    after = before.replace("return 5", "return 4")
    with pytest.raises(EngineError, match="dynamically named fixture"):
        _run(before, after, path="tests/conftest.py")


def test_unchanged_irrelevant_dynamic_fixture_does_not_block():
    before = (
        "import pytest\nfrom app import answer\n\nPUBLIC_NAME = choose_name()\n\n"
        "@pytest.fixture(name=PUBLIC_NAME)\n"
        "def _unrelated():\n    return 13\n\n\n"
        "@pytest.fixture\n"
        "def answer_value():\n    return 5\n\n\n"
        "def test_answer(answer_value):\n"
        "    assert answer() == answer_value\n"
    )
    after = before.replace("return 5", "return 4")
    verdict, findings = _run(before, after)
    assert [finding for finding in findings if finding.rule == RULE]
    assert verdict == "block"


def test_two_helper_calls_subject_actual_change_is_direction_control():
    before = (
        "from app import answer\n\n\ndef assert_answer(got, oracle):\n"
        "    assert got == oracle\n\n\ndef test_answer():\n"
        "    assert_answer(answer(1), 5)\n"
        "    assert_answer(answer(2), 6)\n"
    )
    after = before.replace("answer(1), 5", "answer(9), 5")
    _verdict, findings = _run(before, after)
    assert not [finding for finding in findings if finding.rule == RULE]


@pytest.mark.parametrize("extension", ["json", "yaml"])
def test_named_residual_external_data_carrier_is_explicit(extension: str):
    before = '{"oracle": 5}\n' if extension == "json" else "oracle: 5\n"
    after = before.replace("5", "4")
    consumer = (
        "from app import answer\n\n\n"
        "def test_answer(loaded_cases):\n"
        "    assert answer() == loaded_cases['oracle']\n"
    )
    _verdict, findings = _run(
        before,
        after,
        path=f"tests/expected.{extension}",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]


def test_named_residual_imported_constant_is_explicit():
    before = "BOUND = 5\n"
    after = "BOUND = 4\n"
    consumer = (
        "from .oracles import BOUND\nfrom app import answer\n\n\n"
        "def test_answer():\n    assert answer() == BOUND\n"
    )
    _verdict, findings = _run(
        before,
        after,
        path="tests/oracles.py",
        head={"tests/test_answer.py": consumer},
    )
    assert not [finding for finding in findings if finding.rule == RULE]


def test_matrix_names_every_origin_and_scope():
    assert set(BUILDERS) == {
        "helper_actual",
        "module_table",
        "parametrize",
        "fixture",
        "local",
        "class_attr",
    }
    assert set(POSITIVE_CELLS) == {
        (origin, scope)
        for origin in BUILDERS
        for scope in ("direct", "inherited")
    }
