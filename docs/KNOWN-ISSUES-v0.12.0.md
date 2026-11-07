# Known issues for 0.12.0

Status, 2026-11-07: the 0.12.0 release candidate, prepared in the release
pull request; not a published release record. The publication record follows
once the public files are verified.

0.12.0 narrows #419's residual: in a Python test or conftest the weakening,
stand-in and subject rules take no repair evidence, and in a JS/TS test the
loosening shapes take none ([D-199](../DECISIONS.md)), as Nelson chose for
0.12 ([D-196](../DECISIONS-archive-4.md)). It closes, in part, three holes
beside that residual: an equality with `unittest.mock.ANY`, a single test's
skip that cannot be shown to run anywhere, and `assertEqual` rewritten as
`assertCountEqual` ([D-201](../DECISIONS.md)). And it moves the release tag:
from v0.12.0 the tag points at the release's Action commit A, the commit the
README recommends as the Action pin, while the distributions are still built
from the release merge M ([D-200](../DECISIONS.md)). The
[release guide](releases/v0.12.0-public-launch.md) describes each change and
what this release measured. Both Claude Code hooks are author-side checks:
the required CI check in range mode remains the gate.

This page carries the rows of the 0.12 section of
[KNOWN-ISSUES-next](KNOWN-ISSUES-next.md) into the release's own page; that
section stays there as the dated preparation record, and one cross-reference
here points at the 0.11.0 page instead. The rows below are
named residuals, found by reading the code, its design reviews and toy
repositories unless a row names another source. Earlier limits remain in
[KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md) and the pages it links. A
pass means that no known tampering pattern was detected; it is not a
correctness guarantee.

## Measured for this release, and what was not

- **Fixed-corpus comparison.** On the 3,600 fixed in-sample commits, 19 move
  from pass to block against the published v0.11.0 (8 Python, 11 JS/TS),
  none the other way: D-199's 18 and D-201's rich `655b5210cb` ([release
  guide](releases/v0.12.0-public-launch.md)). Python 1,726 pass and 74
  block, JS/TS 1,748 pass, 50 block and 2 engine errors. In-sample counts,
  not a false-positive rate.
- **A moved test the move credit misses.** One of the 19, rich `b93d3b6d`,
  moves a test unchanged to another file, now importing its subject from the
  module that defines it, beside a one-character fix to the code it tests.
  checkwash does not credit that move, so the disappeared test blocks:
  v0.11.0 held it at warn only by repair evidence, which 0.12.0 refuses. A
  reviewed exemption lets it through.
- **uvloop relays.** The three uvloop regression-test additions that 0.10.0
  blocks still pass on 0.12.0 with no finding
  ([D-190](../DECISIONS-archive-4.md)).
- **D-176's remaining risk, not measured.** An honest broad `except` added
  around an assertion in a Python test or conftest, beside an opaque
  production change, still blocks at high unless D-190 proves it a failure
  relay, exactly as on 0.11.0; how often history holds one is not measured.
  Claude accepts that risk for 0.12.0 only, as a delegated decision ([0.12.0
  disposition](d176-cost-disposition-0.12.0.md)).
- **Not measured:** neither fixed set holds an `== ANY` or an
  `assertCountEqual` rewrite, so those rules' cost is unmeasured. The 1,273
  commits D-201 measured outside both samples, 6 of which moved, informed
  its later review rounds, so that set is no longer out of sample either.

## Limits of the 0.12 changes

| Scope | Known limit and what it means for you |
| --- | --- |
| [#419](https://github.com/taipei49314/checkwash/issues/419) bought repair evidence, narrowed | **Blocks from 0.12:** in a Python test or conftest (any `.py` file), a weakened, removed, skipped or loosened assertion, a broad `except`, a stand-in for the code under test (`TEST_PATCHES_SUBJECT`, `CONFTEST_PATCHES_PROD`, and an import shadow wherever it is reported, a pytest configuration included), a normalized subject, a changed subject input and an expectation derived from the input; in a JS/TS test, a weakened or loosened assertion, a broad catch, a skip added to a live test, and a table left with no row to run (a plain test wrapped in an empty table, or a table emptied where it stands). Each blocks beside any production change, a no-op one included, unless something other than repair evidence holds it: a compatibility `skipif` (D6), a mild weakening inside the exact family (D7), a deletion beside a removed symbol (D8) and the other compensations still apply. Such a finding that the change reached is labelled `REPAIR_EVIDENCE_REFUSED`. A reviewed exemption (`checkwash allow`, merged to the base first), or a maintainer merging past the required check, releases one. **Still passes by default:** a rewritten expected value (`EXPECTED_VALUE_CHANGED`, `EXPECTATION_DEFINITION_CHANGED`, `EXPECTED_VALUE_HARDCODED`) or a substituted assertion (`ASSERT_SUBSTITUTED`) beside a no-op edit, Route A or Route B as in 0.11 (THREATMODEL rows 93 and 130), and two spellings that carry a refused event there: a weakening written as an exact comparison (`assert (total > 0) == True` reads as an expected value changed) and an expectation computed from the subject through a module alias. In JS/TS: a removed assertion, a deleted test or deleted parametrize rows (a plain test paired with a table whose rows cannot be counted reads as a deletion, as tests folded into an imported table do), a test parked where no code runs (`if (false) { test(...) }`), and a stand-in or subject change (`vi.mock`, a `test.each` input cell), each beside any module edit (row 131). A renamed private symbol escorting a test deletion into D8, and D8 counting a row marked off as deleted where the rows cannot be paired (row 56). **Blocks honest changes too:** a deprecated API removed with an assertion on it, a test rewritten beside a behaviour change, and an optional-dependency skip added beside the change that needs it (`pytest.importorskip`, a `find_spec` `skipif`): D6 credits only interpreter and OS conditions on a test's own marker. **Cost, measured on main `7cd8549c`:** 18 of the fixed corpus's 3,600 commits move pass → block (7 Python, 11 JS/TS) and 53 of D-088's 1,263 skip, xfail and conftest commits, none adjudicated; most remove deprecated APIs with their tests, drop old Python versions, or rewrite tests beside a behaviour change. **To block the rest:** `fail-on: warn` in the Action, or a base-side `oracle_freeze` contract in a CLI step ([enterprise checklist §7](enterprise.md#7-hardening-against-bought-repair-evidence-419)); the Claude Code PreToolUse ask covers only the Python test deletion among them, as it asks only on the five weakening rules in a Python test. |
| Three holes beside #419's residual, closed in part ([D-201](../DECISIONS.md)) | **Blocks from 0.12:** an equality with `unittest.mock.ANY` as a whole operand (`assert total() == ANY`, `self.assertEqual(total(), mock.ANY)`, `assertAlmostEqual(total(), ANY)`, `== ANY == 6`, `not (total() != ANY)`, `pytest.approx(ANY)`), membership in a display holding it (`total() in [ANY]`), a padded tuple that checks no position (`(total(), 0) == (ANY, 0)`), `items() == [ANY] * len(items())`, `ANY in items()`, a name the test binds to `ANY`, and a display of nothing but `ANY` (nested, `[ANY] * 3`, a comprehension, `dict(total=ANY)`, against `assertCountEqual` too), which checks only its shape: rewriting an expected value into one is a weakening, beside a version bump or not (`ANY` is read through the file's imports); a single test's skip whose condition cannot be shown false in any supported environment, such as an always-true version check `and`, or a platform check `or`, a call checkwash cannot read, a gate that lets the test run only on an x.y.0 release, and a gate added opposite one the test has (`unittest.skipIf` and a strict xfail included); and `assertEqual`, `assertDictEqual`, `assertMultiLineEqual` or a bare `assert ==` -> `assertCountEqual` on the same subject, which stops checking order, or against a dict the values, even with the expected list reordered or the subject hoisted. **Blocks honest changes too:** a skip that joins an interpreter or platform check by `or` to something checkwash cannot read, such as a dependency's version, an environment variable or `hasattr(os, "fork")` (scrapy 583df9f7d0 moved the uvloop skips of five tests into a fixture that also skips on one Twisted version: 110 findings); a gate spelled in a way checkwash does not read (`platform.release()`, `sys.version_info.micro`, the py library's `py.std.sys.platform`); a gate added to a test that then runs only on Pythons older than 3.11 (rich 655b5210cb: four tests) or only on a machine or interpreter outside the matrix (`platform.machine() != "s390x"`); an expectation made `ANY` because the value became generated; and a test made order-blind on purpose with `assertCountEqual`. **Still passes:** `ANY` reached through a parametrize column, a fixture, another module's constant or a call beside a version bump or a production change (an expectation changed); `ANY` as one entry of a display beside other entries, beside the same; a comparison wrapped in another (`(total() == ANY) is True`) or a chain that joins `== ANY` to another operator, beside the same; mock's `call(ANY)` and `assert_called_with(ANY)`, which are not read as assertions; `assertEqual(items(), [1, 2, 3])` -> `assertEqual(set(items()), {1, 2, 3})` beside a production change, an expected value changed; `self.assertTrue(x == ANY)`, as any rewrite inside a truthy spelling does; a suite-level collection control whose guard is unknown everywhere, such as `find_spec(...) is None`; a conftest's collection control beside an opposite gate on the test it drops; and a gate added opposite one a test had that already ran only outside the matrix (on Python 3.10 or older, on FreeBSD, on 32-bit). **Cost, measured on main `54113c06`:** on D-088 2 of 1,263 commits move from pass to block (scrapy 583df9f7d0 and rich 655b5210cb, above), on R29 1 of 3,600 (rich 655b5210cb), and outside both samples 6 of the 1,273 commits in D-088's repositories that touch a skip (pytest's 2007–2013 history: the py library's `py.std.sys.platform`, `getattr(os, '_name', None)`, and a version check `and` a subprocess's output). No other finding changes on D-088 or R29. Neither sample holds an `== ANY` or an `assertCountEqual` rewrite, so those rules' cost is unmeasured. These are counts, not adjudicated false-positive rates. |
| A CLI installed from a release tag | From v0.12.0 a CLI installed through Git from the tag, such as `pipx install git+https://github.com/taipei49314/checkwash@v0.12.0`, is A. A commit cannot name itself, so A's `doctor` holds the previous release's pin on both pin lines, and `checkwash doctor` rejects v0.12.0's own Action pin, the one the README recommends: "workflow analysis incomplete", exit 1. The PyPI package and the pyz are built from M, whose `doctor` accepts A, and the README installs only those. `check`, the Action, pre-commit and the Claude Code hooks never import `doctor`, so they run the same at A and at M. |
| The Release page's source archives | From v0.12.0 the "Source code" archives GitHub attaches to the Release are A's tree, which differs from the sdist's source in `doctor`'s own Action pin line. |
| v0.11.0 stays as published | Its tag stays on M and its recommended pin on `v0.11.0^2^1`, with the pin-updater and zizmor consequences in the `doctor` row of [KNOWN-ISSUES-v0.11.0](KNOWN-ISSUES-v0.11.0.md). From v0.12.0 Dependabot, Renovate, zizmor and `git ls-remote` see the recommended pin as the tag's commit (inferred from those tools' documentation, not run). Upgrade the CLI and its local hooks before the Action pin, as before. |
| The new release path first runs for real at 0.12.0 | The tag, release-event and public-visitor stages, the verdict gate's tag rule and the baseline binding under the new rule have run only on owned synthetic chains on LAPTOP-01AGNPJU (human-authorized local PJU, NOT EC pool). Their first run against a real tag and a real release event is v0.12.0's. A tag cannot be moved, and the release-event capture runs the tools at A, so a failure found after the push may cost a v0.12.1. `tools/own_action_pin.py check --stage tag` runs three local checks before the push. |
| The disabled hosted workflows | On a tag push from v0.12.0, `ci.yml`, `assertion-qualification.yml` and `verdict-gate.yml` would run at A, not at M, and `verdict-gate.yml`'s tag rule fails there by design. They stay disabled; the PJU release chain runs each stage at M. |

## Publication

- **The PyPI description.** PyPI shows the README as built from the release
  merge commit. Its install commands and Action pin still name v0.11.0, the
  release verified before 0.12.0 was published, and its version sentence says
  so; the [GitHub README](https://github.com/taipei49314/checkwash#readme)
  moves them to 0.12.0 once its public files are verified.
- **Install the CLI from PyPI or the pyz.** A CLI installed through Git from
  the v0.12.0 tag is the Action commit A's, and its `doctor` rejects v0.12.0's
  own Action pin; the row *A CLI installed from a release tag* above gives the
  details.
- **`doctor` across the upgrade.** `doctor` 0.11.0 accepts only v0.10.0's
  and v0.11.0's Action pins, so it rejects the 0.12.0 pin (exit 1): upgrade
  the CLI and its local hooks before the Action pin.
