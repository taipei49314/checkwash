# Assertion coverage and regression prevention

Issue [#164](https://github.com/taipei49314/checkwash/issues/164) exposed a
frontend omission: Node assertions were absent from the IR, so downstream
detectors could not see them weaken. A green detector suite cannot establish
coverage of syntax it never included. These checks are in the current source
tree; they do not update an already-published wheel, zipapp or Action pin.

## Review the support inventory independently

[`tests/data/javascript_assertion_support.json`](../tests/data/javascript_assertion_support.json)
records concrete spellings, documented API sources, support status and literal
expected IR forms, strengths and subjects. Its expectations are not generated
from the frontend's matcher table or strength constants. Unsupported syntax,
methods and lookalikes are recorded alongside supported APIs.

The inventory has 136 API/context cases and 248 concrete changes:
weakening, removal, preserving edits and strengthening controls. Every supported
entry has both a removal case and a preserving case. The suite checks the IR,
finding rule, severity and verdict. Tests deliberately disable each assertion
family to establish that an omitted family makes the contract fail.

When extending a frontend, review the upstream API and update this inventory
before copying implementation behavior into expectations. Add both a real loss
and a preserving control; retain unsupported entries until their expectations
can be deliberately changed. This finite inventory is not proof of support for
all JavaScript syntax or future upstream APIs.

```bash
python -m pytest tests/test_assertion_contract.py tests/test_js_coverage.py
python tools/qualify_assertions.py --distribution source --output receipts/source.json
```

## Make unrepresented assertion candidates visible

`checkwash check` scans both sides of changed JS/TS test files for bounded Node
and `expect(...)` candidates. It compares their source positions with assertions
represented by the frontend. A candidate in a file with no recognized test unit,
or inside another assertion, can therefore still produce a diagnostic.

Diagnostics appear on stderr in every output format and in terminal output.
SARIF includes them as tool execution warnings, separate from findings. A base
location is labeled `before`; it is not projected onto the current checkout.
Zero assertions alone do not produce a warning. Coverage warnings do not change
the tampering verdict, severity policy or exit codes.

For a machine-readable report alongside the existing findings JSON:

```bash
checkwash check BASE..HEAD --format json --coverage-report coverage.json
```

The separate report uses UTF-8, LF, sorted keys and no timestamp. Its schema is:

| Field | Meaning |
|---|---|
| `checkwash_coverage_version` | `1`, independent of IR/findings versions |
| `run` | `base`, `head`, `checkwash_version` |
| `scope` | `javascript_assertion_candidates` |
| `status` | `incomplete` if there are gaps; otherwise `no_known_gaps` |
| `files` | Scanned `{path, side}` pairs, including files without candidates |
| `gaps` | `{path, side, line, column, callee, reason}` records |

`side` is `before` or `after`; lines and columns are one-based positions in
BOM-stripped, LF-normalized source. The report requires a file path (`-` is
rejected) so it cannot corrupt stdout's existing machine protocol. JSON findings
and emitted IR keep their existing shapes.

`no_known_gaps` means only that this bounded candidate scan found none. It is
not a completeness claim. File discovery includes `.test.*` and `.spec.*`
JavaScript/TypeScript files, plus Node's default `test/` directories and
`test-*`, `*-test`, `*_test` and exact `test` filenames for JS/CJS/MJS/TS/CTS/MTS.
Generated/build/dependency paths remain excluded. Moving a test into a production
path is checked as removal from test coverage.

The scan resolves bounded static Node ESM/CommonJS imports, renamed and flat
destructured imports, simple local aliases, and Jest/Vitest `expect` imports.
Lexical declarations and function parameters can shadow those bindings; a
lookalike object cannot retain a real assertion's strength. Unresolved assertion
candidates still produce diagnostics. Dynamic module names, arbitrary wrapper
functions, computed properties and template interpolations remain outside this
evidence. This is a bounded static scan, not complete JavaScript scope or
execution modeling. A project requiring broader coverage must review those
boundaries.

## Qualify the bytes that users run

The `assertion qualification` workflow runs the same 248 changes through actual
CLI invocations against temporary Git commits, separately for source, a freshly
installed wheel and a zipapp. Fixture JavaScript is read, never executed. It
checks findings and exit codes, including a clean range and an invalid-ref
engine error. A preserving case must have no findings.

Receipts identify the source commit, source package hash and dirty flag,
artifact hash, reported version, suite hash and each case's result. Artifact
package bytes and the wheel actually imported by the isolated interpreter must
match the selected source. A stale build cannot pass merely because it reports
the same version. The release workflow repeats these checks before artifact
upload and PyPI publication; see [the release procedure](RELEASING.md).

A separate job extracts the full recommended Action SHA from the README and
qualifies that exact installed engine against the current contract. It does not
claim to exercise the composite Action wiring; existing dogfood smoke tests do
that. The recommended v0.4.0 engine predates the Node repair and is expected to
fail those cases. Its red result is retained with a receipt, not waived or
silently re-pinned. A candidate passing the contract therefore does not imply
the older recommended Action has gained the same coverage.

## Require candidate qualification before merging

This repository's `checkwash required` ruleset targets the default branch and
requires `checkwash` plus all three `candidate assertion contract (source)`,
`candidate assertion contract (wheel)` and `candidate assertion contract (pyz)`
checks. Candidate checks are bound to the GitHub Actions app, run on every pull
request without path filters, and must be current with the base branch. Their
names must remain in sync with the ruleset; renaming a workflow job requires
updating the corresponding required context.

The older recommended Action engine is a separate compatibility measurement,
not a substitute for candidate qualification. Its known missing capabilities
remain visible. A passing required check does not erase failures in other
release or compatibility checks. The downstream Action ruleset example retains
only `checkwash`, since consumers do not run this repository's development jobs.
