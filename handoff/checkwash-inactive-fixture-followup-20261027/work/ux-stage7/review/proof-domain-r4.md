# Inactive-fixture proof domain — development r4

This describes the bounded implementation frozen for `inactive-fixture-r4`.
It is an optional source proof for the #358 relocation shape, not a general
pytest/runtime equivalence result or release acceptance. The analyzed fixture,
producer and test programs are source bytes and were not executed.

## Source and actual evidence

The worktree is `work/checkwash-inactive-fixture`, based on
`fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`. At this receipt the changes were
uncommitted development inputs; that BASE SHA does not identify the changed
product bytes. `wip-history/development-r4/manifest.json` preserves all six
changed source/test files with these raw SHA256 values:

| Path | SHA256 |
| --- | --- |
| `src/checkwash/engine.py` | `881325f81c6b79dc98f0dfa54dd9026a956efc6ab8e71d6616da3d545efecaff` |
| `src/checkwash/oracle_credit.py` | `bca94a04bc2f881a5b7adf8db8a94c992b622b70d10915bc1639d49034f31db7` |
| `src/checkwash/oracle_fixture_credit.py` | `d3f3be535ebf6deb360d013eb7d0565e3878b73049b5d93a18298fe5ef6a52de` |
| `tests/test_inactive_fixture_context_reader.py` | `2f1e07c7a89ceb93075b8e86e59d4b03af54a1f86533df492627803ff57390d2` |
| `tests/test_inactive_fixture_oracle_credit.py` | `e6c0520a9b9a35ae8387afd9cba21543e3610dae7ed9c108fc1d9055b703ba80` |
| `tests/test_issue358_own_mark_guards.py` | `a008186708b6dcd46d166446f7320a948326d987fd409137900606bbf5f6622b` |

The manifest SHA256 is
`d7406a73116b0d2c81341d8dc86a3406156e4a7c2d0a562acbead99f048a543b`.
The native r4 receipt is
`root/inactive-fixture-r4/receipt.json` (SHA256
`46502e670d447bdea0f498f30576ab3e8af12762339e3f8292d60fe334326148`),
and native `junit.xml` is
`dbbca2a512f6364108c6e61723107417c66b385a02298262b08d0e29e38f3410`.
The actual result is **323 tests, zero failures/errors/skips, exit 0** on
`LAPTOP-01AGNPJU`, Windows, Python 3.11.9, marked
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. The receipt records
`source_files_unchanged=true`, `changed_inputs=[]`, and input-manifest SHA256
`256074c9d24bc24c0cfc91aea7d3bce49bb5bf14250abe397ecc9fe788261732`.
This is `WORKING_TREE_DEVELOPMENT_NOT_COMMIT_QUALIFICATION`.

The immediately preceding r3 retains its actual one failure / 322 passes:
bare `@pytest.mark.parametrize` on a sibling incorrectly allowed the selected
unit's move credit. R4 changes exactly the helper's one-line bare-mark
predicate to reject `parametrize`; the same 323 expectations then pass. The
prior failing receipts, snapshots and source-only review findings remain
historical evidence rather than being overwritten or treated as PASS.

## API and three explicit authorities

```python
@dataclass(frozen=True)
class InactiveFixtures:
    fixture_node_ids: frozenset[int]
    request_node_ids: frozenset[int]
    certificates: dict[str, str]

def prove_inactive_fixtures(source, tree, functions, *, path, read,
                            search=None, path_lister=None) -> InactiveFixtures | None:
    ...
```

1. `read(relative_path)` provides strict, side-correct bytes or known absence
   (`None`). Reader errors, nonregular/opaque paths, invalid types and refused
   reads are unknown. No bound-method introspection borrows another capability.
2. `search([""])` independently provides the complete **nonempty Python**
   inventory. Missing search is unknown, not an empty repository. It is called
   once per helper invocation. Every canonical `.py` file in the all-file list
   is read, and nonempty presence must agree exactly with this inventory.
3. `path_lister()` independently provides the complete **all-file** inventory,
   including empty files and non-Python configs. Missing metadata is unknown.
   Every read, including cache hits, checks this authority first. Exact file
   presence must agree with bytes versus `None`; a known case alias, directory
   at the requested file, or file at an ancestor is not known absence.

The engine obtains these authorities explicitly from its root callbacks and
reconstructs each BASE/HEAD view from captured changes. It includes additions,
deletions, both rename ends and explicit source recreation, refuses conflicting
actual observations independently of record order, and uses the unchanged HEAD
reader only for genuinely unchanged paths. Refused reads/discovery remain
cached unknown. D10 survivor checks use the HEAD side. The caller still requires
known startup before invoking this helper; a successful single-side proof does
not establish equivalence to another side.

## Exact budgets and path restrictions

| Layer | Bound |
| --- | --- |
| Engine reconstructed complete file metadata | At most 512 paths per side |
| Helper complete all-file metadata | At most 256 paths |
| Engine and helper nonempty Python inventory | Fewer than 64 paths |
| Engine source cache | At most 256 entries; changed sides are separate keys, unchanged observations are shared |
| Engine source bytes | 2 MiB aggregate; at most 65,536 bytes per returned source |
| Helper source cache | At most 128 entries, including the supplied selected source and absent probes |
| Helper source bytes | 1 MiB aggregate; at most 65,536 bytes each, including selected source |
| Helper AST | At most 4,096 nodes per parsed source; supplied selected function map at most 128 entries |
| Helper path depth | At most 16 components |

Paths are safe lexical relative names with normalized `/` separators. Empty,
absolute, drive/colon, control-character, `.`/`..`, opaque trailing-directory
and duplicate names withhold proof. Complete metadata rejects file/directory
casefold collisions and aliases, noncanonical-case `.PY` variants,
`conftest.py`, `__init__.py` and pytest configuration basenames. Any component
ending case-insensitively in `.egg-info` or `.dist-info` is rejected, including
a standalone metadata file: repository distribution metadata can load a
`pytest11` plugin. These are admission checks, not filesystem resolution.
The caller must still refuse symlinks and other nonregular source reads.

## Supported module, fixture and unit grammar

The selected module and **every actual collectable sibling** undergo the same
complete module check, with no recursive inventory call, filtered search,
substitute source or hidden sibling path. An empty/literal-only module or the
retained old module containing only the same fixture may be a harmless sibling
without earning any unit certificate. An unknown sibling withholds the entire
optional module proof.

Module statements are limited to docstrings/pass, unique exact `import pytest`
and/or `import os`, absolute `from package.module import function` bindings,
plain test functions and at most one supported fixture. Every producer import,
including an unused import, has to satisfy the closed import/startup proof.
No arbitrary assignment, helper class/function, bootstrap call, hook or binding
reassignment is admitted. Noncanonical bindings reject private names and
casefold `pytest*`, `setup*`, `teardown*` and `request`; fixture names additionally
reject `test*`. This excludes pytest module protocols and xunit callbacks.
Compiler-reserved `__debug__` bindings are rejected in consumers and producers.
Canonical framework decorators must have their import available at definition
time. Same-basename collected modules conservatively withhold proof without a
separate package/import-mode proof.

The single selected fixture must be exactly a synchronous function with one
unannotated `request` argument, no defaults/other parameters/return annotation,
and one canonical `@pytest.fixture(autouse=True)` decorator. Explicit
`scope='function'` is also accepted; other options or scopes are unknown.
Its body is exactly one `if`, no `else`, prefix or suffix. The condition is an
AND whose first operand is exactly
`request.node.get_closest_marker('literal-marker')`. The remaining operands
are only closed bool/not/AND/OR expressions and `os.environ.get` with one or
two literal arguments, a bounded nonempty literal string key and no keywords.
The body is exactly `pytest.skip('literal-reason')`. There is no arbitrary tail
call even when the selected unit lacks the marker: a marked sibling could run
that tail first. The whole fixture rejects async, yield/yield-from (including
unreachable occurrences), nested definitions/classes, global/nonlocal writes,
named expressions and other unsupported compiler/runtime constructs.

Certificate-eligible units are plain, undecorated, top-level, no-argument test
functions whose complete OwnMarks result is known and lacks the fixture's
marker. Their bodies contain only docstrings/pass and supported assertions
over primitive literal expressions and closed imported calls. At least one
actual imported call is required; empty-call purity is never a whole-unit
proof. Marked units receive no certificate and cannot borrow a sibling's.
For sibling closure only, bare canonical marker attributes may be admitted;
bare `parametrize` is explicitly unknown because pytest consumes its missing
mandatory arguments during collection. Decorator calls are outside this domain.

Every reachable test call must target an unambiguously resolved absolute
`from` import, with closed literal arguments and complete positional/keyword/
default binding: missing/extra/duplicate arguments and unknown keywords are
rejected. Producer signatures do not admit positional-only, keyword-only,
variadic or annotated/generic forms. Producer modules satisfy the existing
primitive purity grammar **and** this helper's stricter rejection of every
import and call anywhere in that producer AST. Thus opaque helpers, builtin or
method calls, reflection, frame/caller/receiver identity and external mutation
do not gain credit from a boolean purity answer. No producer is evaluated.

## Startup, certificate and caller obligations

All inventoried conftests, including nonancestor ones capable of installing
global collection hooks, must be inert. Relevant test-package initializers,
conventional startup modules and imported producer package initializers must
be known absent or inert. Canonical framework lookup roots must not contain
local `pytest`/`os` replacements. Configuration probes cover `pytest.ini`,
`.pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `pytest.toml` and
`.pytest.toml`. Only the existing narrow default-collection grammar (empty
options or supported literal descendant-directory testpaths covering this
consumer) is admitted; ordinary pyproject data without pytest options may be
allowed. Structured plugin keys and repository distribution metadata refuse
this optional proof. Unknown configuration does not mean default settings.

Certificates bind a versioned domain, the exact fixture name/marker/decorator/
condition/body shape, each actual call's complete binding and the sorted path/
SHA256-or-absence identities of observed nonconsumer sources. Producer source
changes therefore do not become cross-side equivalence merely because both
sources are pure or return the same literal. All actual source reads remain
subject to the engine's side-aware evidence recording.

Only fully validated collectable consumer modules are excluded from that
dependency identity list. Their source bytes/names/counts would otherwise make
an old retained fixture-only module differ from its legitimate arrival. The
projection is permitted only after the whole module's imports, declarations,
fixtures and every unit body satisfy the closed no-external-mutation grammar.
Producer, initializer, config and absence identities are retained. The helper
certificate contains no selected filename, qualname, line number or node ID.
The caller's existing declaration/environment/body proof still applies; it
retains the full fixture AST and adds the new per-unit certificate scope.

Returned node IDs refer to the **same supplied tree** and are not serialized
proof inputs. The caller may exempt only those exact fixture/request nodes,
and must require the current unit's own valid certificate before generating
its unit/assertion context. Unknown or marked units cannot use the union of
another unit's allowed IDs. Source parsing and proof serialization must not
mutate the caller tree. Default contexts outside this optional fixture domain
retain their previous proof scope.

## Conservative costs and remaining verification boundary

Missing/failed/type-invalid capabilities, conflicting side data, alias/opaque
paths, budgets, large repositories, unusual collection/import mode, active
initializers or conftests, executable/unproved siblings, local framework
replacements, plugin metadata, unknown pytest options, multiple/noncanonical
fixtures, classes, parameters, decorators, opaque callees and broader otherwise
legitimate refactors may all remain UNKNOWN. Even harmless empty-file/policy/
producer changes can alter retained dependency identities. This withholds
optional relocation credit; independent existing detectors and repair evidence
keep their own behavior. It is not an automatic assertion that a program is
malicious, nor a promise that the overall verdict must BLOCK when another
independent D1 repair-evidence path applies.

Ambient externally installed plugins, external import hooks and a changed
runtime/framework outside the supplied repository snapshot are outside this
bounded source model. The three capabilities must be honest complete strict
snapshots with the caller's startup/environment obligations; similar-looking
interfaces or absent responses alone are not authority. Repository-visible
plugin hooks/metadata are within scope and rejected as described above.

R4 establishes only the recorded 323 development controls on Windows/Python
3.11.9. New-source full-suite, wheel/pyz/source qualification, release bridge,
publication, Python 3.12/3.13 and other operating systems are **NOT_RUN by this
receipt**. Prior fbc or stage5 receipts are not inherited by these changed bytes.
No golden verdict labels, gating severity, strength/alignment parameters or
protected contracts were changed by this helper work. Independent bounded
readback and a draft commit do not turn this evidence into complete semantic
safety, complete goal acceptance or release PASS.
