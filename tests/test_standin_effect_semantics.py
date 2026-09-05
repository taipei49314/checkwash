from __future__ import annotations

import pytest

from checkwash.frontends.python import parse_python
from checkwash.ir.model import Assertion, UnitSide
from checkwash.standins import (
    StandinInstall,
    effect_oracle_multisets,
    install_reaches,
    new_reaching_effects,
    new_unit_standin_installs,
)


IMPORTS = {"billing": "app.billing"}


def _assertion(
    position: tuple[int, int],
    *,
    key: str | None = "same-oracle",
    text: str = "assert billing.total() == expected",
    left: str = "billing.total()",
    imports: dict[str, str] | None = None,
    runtime_imports: tuple[
        tuple[str, str, str, int, int], ...
    ] = (),
) -> Assertion:
    return Assertion(
        id=f"oracle-{position[0]}-{position[1]}",
        form="compare_eq",
        strength=3,
        text=text,
        span=(0, 0),
        left=left,
        right_depends_on=("expected",),
        standin_imports=IMPORTS if imports is None else imports,
        standin_runtime_imports=runtime_imports,
        standin_position=position,
        standin_oracle_key=key,
    )


def _install(
    position: tuple[int, int],
    *,
    active_until: tuple[int, int] | None = None,
    text: str = "billing.total = reference",
) -> StandinInstall:
    return StandinInstall(
        target="app.billing.total",
        attr="total",
        text=text,
        scope="test",
        position=position,
        active_until=active_until,
    )


def _side(
    assertions: list[Assertion],
    installs: tuple[StandinInstall, ...],
) -> UnitSide:
    return UnitSide(
        span=(0, 0),
        assertions=assertions,
        standin_imports=IMPORTS,
        standin_installs=installs,
    )


def _parsed_side(source: str) -> UnitSide:
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    assert len(parsed.units) == 1
    return parsed.units[0].side


def test_active_window_reaches_inside_but_not_at_or_after_endpoint():
    install = _install((2, 4), active_until=(5, 0))

    # Lifetime is internal analysis evidence, not effect/newness identity.
    assert install == _install((2, 4))

    assert install_reaches(
        install,
        _side([_assertion((4, 4))], (install,)),
        IMPORTS,
    )
    assert not install_reaches(
        install,
        _side([_assertion((5, 0))], (install,)),
        IMPORTS,
    )
    assert not install_reaches(
        install,
        _side([_assertion((6, 4))], (install,)),
        IMPORTS,
    )


@pytest.mark.parametrize("local", ["invoice_total", "total"])
@pytest.mark.parametrize(
    "import_location,expected",
    [
        ("module", False),
        ("before", False),
        ("after", True),
    ],
)
def test_attribute_patch_respects_leaf_import_capture_time(
    local: str,
    import_location: str,
    expected: bool,
):
    import_line = (
        f"from app.billing import invoice_total as {local}\n"
        if local != "invoice_total"
        else "from app.billing import invoice_total\n"
    )
    module_import = import_line + "\n" if import_location == "module" else ""
    before_patch = (
        "    " + import_line if import_location == "before" else ""
    )
    after_patch = (
        "    " + import_line if import_location == "after" else ""
    )
    source = (
        "from unittest import mock\n"
        + module_import
        + "def _reference(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        + before_patch
        + "    mock.patch(\n"
        "        'app.billing.invoice_total', _reference\n"
        "    ).start()\n"
        + after_patch
        + f"    assert {local}([], 0) == 105.3\n"
    )
    side = _parsed_side(source)
    assert len(side.standin_installs or ()) == 1
    install = (side.standin_installs or ())[0]

    assert install_reaches(
        install, side, side.standin_imports or {}
    ) is expected


def test_attribute_patch_keeps_live_module_object_alias_reachable():
    source = (
        "from unittest import mock\n"
        "import app.billing as bills\n\n"
        "def _reference(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        "    mock.patch(\n"
        "        'app.billing.invoice_total', _reference\n"
        "    ).start()\n"
        "    assert bills.invoice_total([], 0) == 105.3\n"
    )
    side = _parsed_side(source)
    install = (side.standin_installs or ())[0]

    assert install_reaches(install, side, side.standin_imports or {})


@pytest.mark.parametrize(
    "import_before_install,expected",
    [(True, False), (False, True)],
)
def test_same_file_module_patch_respects_leaf_import_order(
    import_before_install: bool,
    expected: bool,
):
    leaf_import = "from app.billing import invoice_total\n"
    install = (
        "mock.patch(\n"
        "    'app.billing.invoice_total', _reference\n"
        ").start()\n"
    )
    source = (
        "from unittest import mock\n\n"
        "def _reference(*args):\n"
        "    return 105.3\n\n"
        + (leaf_import + install if import_before_install else install + leaf_import)
        + "\ndef test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    side = _parsed_side(source)
    module_installs = tuple(
        candidate
        for candidate in side.standin_installs or ()
        if candidate.scope == "module"
    )
    assert len(module_installs) == 1

    assert install_reaches(
        module_installs[0], side, side.standin_imports or {}
    ) is expected


def test_cross_file_module_patch_precedes_consumer_module_leaf_import():
    target = "app.billing.invoice_total"
    install = StandinInstall(
        target=target,
        attr="invoice_total",
        text="conftest module patch",
        scope="module",
        position=(200, 0),
    )
    assertion = _assertion(
        (8, 4),
        left="invoice_total([], 0)",
        text="assert invoice_total([], 0) == expected",
        imports={"invoice_total": target},
    )
    assertion.standin_module_imports = (
        ("invoice_total", target, "app.billing", 1, 0),
    )
    side = UnitSide(
        span=(0, 0),
        assertions=[assertion],
        standin_imports={"invoice_total": target},
        standin_installs=(),
    )

    assert install_reaches(install, side, side.standin_imports or {})


@pytest.mark.parametrize(
    "subject_setup,subject,expected",
    [
        (
            "from app.billing import invoice_total\n",
            "invoice_total([], 0)",
            False,
        ),
        (
            "",
            "invoice_total([], 0)",
            True,
        ),
        (
            "import app.billing as bills\n",
            "bills.invoice_total([], 0)",
            True,
        ),
    ],
)
def test_class_decorator_leaf_capture_and_live_alias_controls(
    subject_setup: str,
    subject: str,
    expected: bool,
):
    runtime_import = (
        "        from app.billing import invoice_total\n"
        if not subject_setup
        else ""
    )
    source = (
        "from unittest import mock\n"
        + subject_setup
        + "\n@mock.patch(\n"
        "    'app.billing.invoice_total', lambda *_: 105.3\n"
        ")\n"
        "class TestBilling:\n"
        "    def test_total(self):\n"
        + runtime_import
        + f"        assert {subject} == 105.3\n"
    )
    side = _parsed_side(source)
    install = next(
        candidate
        for candidate in side.standin_installs or ()
        if candidate.scope == "class"
    )

    assert install_reaches(
        install, side, side.standin_imports or {}
    ) is expected


@pytest.mark.parametrize("install_scope", ["module", "early_hook"])
def test_conftest_pre_import_phase_reaches_top_level_leaf(
    install_scope: str,
):
    setup = (
        "mock.patch(\n"
        "    'app.billing.invoice_total', lambda *_: 105.3\n"
        ").start()\n"
        if install_scope == "module"
        else (
            "def pytest_configure():\n"
            "    mock.patch(\n"
            "        'app.billing.invoice_total', lambda *_: 105.3\n"
            "    ).start()\n"
        )
    )
    conftest = parse_python(
        ("from unittest import mock\n\n" + setup).encode(),
        collect_tests=True,
        conftest=True,
    )
    install = next(
        candidate
        for candidate in conftest.standin_installs
        if candidate.target == "app.billing.invoice_total"
    )
    consumer = _parsed_side(
        "from app.billing import invoice_total\n\n"
        "def test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )

    assert install_reaches(
        install, consumer, consumer.standin_imports or {}
    )


@pytest.mark.parametrize("runtime_import", [False, True])
def test_conftest_fixture_leaf_requires_runtime_import(runtime_import: bool):
    conftest = parse_python(
        (
            "from unittest import mock\n"
            "import pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def adapter():\n"
            "    with mock.patch(\n"
            "        'app.billing.invoice_total', lambda *_: 105.3\n"
            "    ):\n"
            "        yield\n"
        ).encode(),
        collect_tests=True,
        conftest=True,
    )
    install = next(
        candidate
        for candidate in conftest.standin_installs
        if candidate.scope == "fixture"
    )
    import_line = (
        "    from app.billing import invoice_total\n"
        if runtime_import
        else "from app.billing import invoice_total\n\n"
    )
    consumer = _parsed_side(
        (
            ("" if runtime_import else import_line)
            + "def test_total():\n"
            + (import_line if runtime_import else "")
            + "    assert invoice_total([], 0) == 105.3\n"
        )
    )

    assert install_reaches(
        install, consumer, consumer.standin_imports or {}
    ) is runtime_import


@pytest.mark.parametrize("runtime_import", [False, True])
def test_fixture_carrier_oracle_preserves_leaf_import_provenance(
    runtime_import: bool,
):
    module_import = (
        ""
        if runtime_import
        else "from app.billing import invoice_total\n"
    )
    local_import = (
        "    from app.billing import invoice_total\n"
        if runtime_import
        else ""
    )
    parsed = parse_python(
        (
            "import pytest\n"
            "from app import billing\n"
            + module_import
            + "\ndef _reference(*args):\n"
            "    return 105.3\n\n"
            "@pytest.fixture\n"
            "def verify(monkeypatch):\n"
            "    monkeypatch.setattr(\n"
            "        billing, 'invoice_total', _reference\n"
            "    )\n"
            + local_import
            + "    assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
        conftest=True,
    )
    assertion = parsed.fixture_asserts["verify"][0]
    install = next(
        candidate
        for candidate in parsed.standin_installs
        if candidate.scope == "fixture"
    )
    side = UnitSide(
        span=(0, 0),
        assertions=[assertion],
        standin_imports={},
        standin_installs=(),
    )

    assert install_reaches(install, side, {}) is runtime_import


@pytest.mark.parametrize("runtime_import", [False, True])
def test_invoked_helper_oracle_preserves_projected_leaf_import(
    runtime_import: bool,
):
    module_import = (
        ""
        if runtime_import
        else "from app.billing import invoice_total\n"
    )
    helper_import = (
        "    from app.billing import invoice_total\n"
        if runtime_import
        else ""
    )
    side = _parsed_side(
        "from unittest import mock\n"
        "import app.billing as billing\n"
        + module_import
        + "\ndef _reference(*args):\n"
        "    return 105.3\n\n"
        "def verify():\n"
        + helper_import
        + "    assert invoice_total([], 0) == 105.3\n\n"
        "def test_total():\n"
        "    mock.patch(\n"
        "        'app.billing.invoice_total', _reference\n"
        "    ).start()\n"
        "    verify()\n"
    )
    install = next(
        candidate
        for candidate in side.standin_installs or ()
        if candidate.scope == "test"
    )
    inherited = next(
        assertion for assertion in side.assertions if assertion.inherited
    )
    assert inherited.standin_runtime_imports_projected

    assert install_reaches(
        install, side, side.standin_imports or {}
    ) is runtime_import


def test_fresh_unconsumed_leaf_alias_does_not_bless_captured_subject():
    target = "app.billing.invoice_total"
    install = StandinInstall(
        target=target,
        attr="invoice_total",
        text="patch invoice_total",
        scope="test",
        position=(5, 4),
    )
    assertion = _assertion(
        (9, 4),
        left="captured([], 0)",
        text="assert captured([], 0) == expected",
        imports={"captured": target, "fresh": target},
        runtime_imports=(("fresh", target, "app.billing", 7, 4),),
    )
    side = UnitSide(
        span=(0, 0),
        assertions=[assertion],
        standin_imports={"captured": target, "fresh": target},
        standin_installs=(install,),
    )

    assert not install_reaches(
        install, side, side.standin_imports or {}
    )


def test_binding_replacement_still_reaches_renamed_bare_local():
    install = StandinInstall(
        target="app.billing.invoice_total",
        attr="renamed",
        text="renamed = _reference",
        scope="test",
        kind="binding",
        position=(5, 4),
    )
    assertion = _assertion(
        (7, 4),
        left="renamed([], 0)",
        text="assert renamed([], 0) == expected",
        imports={},
    )
    side = UnitSide(
        span=(0, 0),
        assertions=[assertion],
        standin_imports={},
        standin_installs=(install,),
        standin_lexical_names=("renamed",),
    )

    assert install_reaches(install, side, {})


@pytest.mark.parametrize(
    "scope,owner",
    [
        ("fixture", "adapter"),
        ("class", "TestBilling"),
        ("class_fixture", "TestBilling.adapter"),
        ("hookwrapper", "pytest_runtest_call"),
        ("hook", "pytest_runtest_setup"),
    ],
)
def test_post_collection_install_requires_fresh_leaf_import(
    scope: str,
    owner: str,
):
    target = "app.billing.invoice_total"
    install = StandinInstall(
        target=target,
        attr="invoice_total",
        text="patch invoice_total",
        scope=scope,
        owner=owner,
        position=(200, 0),  # Deliberately a different source-file range.
    )
    captured = _assertion(
        (8, 4),
        left="invoice_total([], 0)",
        text="assert invoice_total([], 0) == expected",
        imports={"invoice_total": target},
    )
    fresh = _assertion(
        (8, 4),
        left="invoice_total([], 0)",
        text="assert invoice_total([], 0) == expected",
        imports={"invoice_total": target},
        runtime_imports=(
            ("invoice_total", target, "app.billing", 6, 4),
        ),
    )

    assert not install_reaches(
        install,
        UnitSide(
            span=(0, 0),
            assertions=[captured],
            standin_imports={"invoice_total": target},
            standin_installs=(),
        ),
        {"invoice_total": target},
    )
    assert install_reaches(
        install,
        UnitSide(
            span=(0, 0),
            assertions=[fresh],
            standin_imports={"invoice_total": target},
            standin_installs=(),
        ),
        {"invoice_total": target},
    )


def test_same_effect_instances_count_each_oracle_occurrence_once():
    dead = _install((6, 4), text="a dead spelling")
    live = _install((2, 4), text="z live spelling")
    side = _side([_assertion((5, 4))], (dead, live))

    oracles, reached, representatives = effect_oracle_multisets(
        side, IMPORTS
    )

    assert oracles == {"same-oracle": 1}
    assert reached[live.effect_identity] == {"same-oracle": 1}
    assert representatives[live.effect_identity] == live


@pytest.mark.parametrize(
    "after_scope,after_owner,after_autouse",
    [
        ("fixture", "renamed_adapter", False),
        ("fixture", "adapter", True),
        ("test", None, False),
    ],
)
def test_execution_registration_does_not_split_semantic_effect_identity(
    after_scope: str,
    after_owner: str | None,
    after_autouse: bool,
):
    before_install = StandinInstall(
        target="app.billing.total",
        attr="total",
        text="adapter patch",
        scope="fixture",
        owner="adapter",
        autouse=False,
        position=(2, 4),
    )
    after_install = StandinInstall(
        target="app.billing.total",
        attr="total",
        text="refactored patch",
        scope=after_scope,
        owner=after_owner,
        autouse=after_autouse,
        position=(2, 4),
    )
    assertions = [_assertion((5, 4))]

    assert before_install.effect_identity == after_install.effect_identity
    assert new_reaching_effects(
        _side(assertions, (before_install,)),
        _side(assertions, (after_install,)),
    ) == ()


def test_moving_an_existing_effect_before_an_existing_oracle_is_new():
    late = _install((8, 4))
    early = _install((2, 4))
    before = _side([_assertion((5, 4))], (late,))
    after = _side([_assertion((5, 4))], (early,))

    assert new_reaching_effects(before, after) == (early,)
    assert new_unit_standin_installs(before, after) == (early,)


def test_new_identical_oracle_spends_the_reach_increase():
    install = _install((4, 4))
    before = _side([_assertion((2, 4))], (install,))
    after = _side(
        [_assertion((2, 4)), _assertion((6, 4))],
        (install,),
    )

    assert new_reaching_effects(before, after) == ()
    assert new_unit_standin_installs(before, after) == ()


def test_expanding_a_context_window_to_an_existing_oracle_is_new():
    bounded = _install((2, 4), active_until=(5, 0))
    persistent = _install((2, 4))
    assertions = [_assertion((6, 4))]

    assert new_reaching_effects(
        _side(assertions, (bounded,)),
        _side(assertions, (persistent,)),
    ) == (persistent,)


def test_reach_is_compared_per_oracle_shape_not_only_in_total():
    first_only = _install((2, 4), active_until=(5, 0))
    second_only = _install((5, 4))
    assertions = [
        _assertion((3, 4), key="oracle-a"),
        _assertion((7, 4), key="oracle-b"),
    ]

    assert new_reaching_effects(
        _side(assertions, (first_only,)),
        _side(assertions, (second_only,)),
    ) == (second_only,)


def test_oracle_key_prefers_internal_canonical_shape_and_has_rich_fallback():
    install = _install((1, 0))
    canonical = _side(
        [
            _assertion(
                (2, 0),
                key="canonical",
                text="assert billing.total()==expected",
            ),
            _assertion(
                (3, 0),
                key="canonical",
                text="assert billing.total() == expected + 1",
            ),
        ],
        (install,),
    )
    fallback = _side(
        [
            _assertion(
                (2, 0),
                key=None,
                text="assert billing.total()==expected",
            ),
            _assertion(
                (3, 0),
                key=None,
                text="assert billing.total() == expected + 1",
            ),
        ],
        (install,),
    )

    canonical_oracles, _, _ = effect_oracle_multisets(canonical, IMPORTS)
    fallback_oracles, _, _ = effect_oracle_multisets(fallback, IMPORTS)

    assert canonical_oracles == {"canonical": 2}
    assert len(fallback_oracles) == 2


def test_external_ir_v1_patch_fallback_stays_available():
    before = UnitSide(span=(0, 0), patches=())
    after = UnitSide(
        span=(0, 0),
        patches=(("app.billing.total", "total"),),
    )

    assert new_unit_standin_installs(before, after) == (
        StandinInstall(
            target="app.billing.total",
            attr="total",
            text="app.billing.total",
            scope="test",
            display_target="app.billing.total",
        ),
    )


def test_binding_candidates_survive_until_provider_ownership_is_known():
    def provider_assertion(identifier: str, provider: str | None) -> Assertion:
        return Assertion(
            id=identifier,
            form="compare_eq",
            strength=3,
            text="assert slot() == 1",
            span=(0, 0),
            left="slot()",
            standin_imports=(
                {"slot": provider} if provider is not None else {}
            ),
            standin_position=(2, 0),
            standin_oracle_key="slot-oracle",
            reaching=(
                {} if provider is not None else {"slot": "lambda: 1"}
            ),
        )

    before = UnitSide(
        span=(0, 0),
        assertions=[
            provider_assertion("external", "aardvark.fn"),
            provider_assertion("owned", "app.fn"),
        ],
        standin_imports={},
        standin_installs=(),
    )
    after = UnitSide(
        span=(0, 0),
        assertions=[
            provider_assertion("external", None),
            provider_assertion("owned", None),
        ],
        standin_imports={},
        standin_installs=(),
        standin_lexical_names=("slot",),
    )

    assert {
        install.target for install in new_unit_standin_installs(before, after)
    } == {"aardvark.fn", "app.fn"}


@pytest.mark.parametrize(
    "after_import,after_setup,replacement_target",
    [
        (
            "from app.billing import invoice_total as new\n",
            "    new = _reference\n",
            None,
        ),
        (
            "from tests.reference import total as new\n",
            "",
            "tests.reference.total",
        ),
    ],
)
def test_provider_replacement_survives_bare_import_alias_rename(
    after_import: str,
    after_setup: str,
    replacement_target: str | None,
):
    before = _parsed_side(
        "from app.billing import invoice_total as old\n\n"
        "def test_total():\n"
        "    assert old([], 0) == 105.3\n"
    )
    after = _parsed_side(
        after_import
        + "\ndef _reference(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        + after_setup
        + "    assert new([], 0) == 105.3\n"
    )

    installs = new_unit_standin_installs(before, after)

    assert len(installs) == 1
    install = installs[0]
    assert install.kind == "binding"
    assert install.target == "app.billing.invoice_total"
    assert install.attr == "new"
    assert install.replacement_target == replacement_target
    assert install_reaches(
        install, after, after.standin_imports or {}
    )


def test_bare_import_alias_rename_with_same_provider_is_not_new():
    before = _parsed_side(
        "from app.billing import invoice_total as old\n\n"
        "def test_total():\n"
        "    assert old([], 0) == 105.3\n"
    )
    after = _parsed_side(
        "from app.billing import invoice_total as new\n\n"
        "def test_total():\n"
        "    assert new([], 0) == 105.3\n"
    )

    assert new_unit_standin_installs(before, after) == ()


def test_renamed_local_implementations_do_not_borrow_import_provenance():
    before = _parsed_side(
        "def old(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        "    assert old([], 0) == 105.3\n"
    )
    after = _parsed_side(
        "def new(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        "    assert new([], 0) == 105.3\n"
    )

    assert new_unit_standin_installs(before, after) == ()


def test_unused_import_alias_rename_does_not_relabel_local_subject():
    before = _parsed_side(
        "from app.billing import invoice_total as old\n\n"
        "def _reference(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        "    subject = _reference\n"
        "    assert subject([], 0) == 105.3\n"
    )
    after = _parsed_side(
        "from app.billing import invoice_total as new\n\n"
        "def _reference(*args):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        "    subject = _reference\n"
        "    assert subject([], 0) == 105.3\n"
    )

    assert new_unit_standin_installs(before, after) == ()
