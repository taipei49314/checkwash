# Independent bounded source readback — e13b helper

State: BLOCKED_ON_B7_SOURCE_ONLY. This is a read-only source assessment, not
a pytest, compilation, prototype, native fixture execution or cross-platform
result. The helper reviewed is e13b2ed785958dc56745b7097a806443e638722c0178bd62116cb8a81d448e93;
engine is 881325f81c6b79dc98f0dfa54dd9026a956efc6ab8e71d6616da3d545efecaff;
oracle integration is bca94a04bc2f881a5b7adf8db8a94c992b622b70d10915bc1639d49034f31db7.
All sources are development working-tree bytes based on fbc9374d, not a sealed
release or a commit that already contains the work. Root owns actual captures.
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL, LAPTOP-01AGNPJU.

## B1–B5 and previously identified protocol names

The actual source repairs were read back, without claiming their runtime result:

- Engine1718–1777 coalesces actual observations independently on each side,
  rejects conflicts lazily, and caches failed reads before invoking ROOT. An
  added recreation does not erase rename-source BASE bytes.
- Engine1779–1822 reserves common raw inventory failure once, overlays the
  appropriate side's captured bytes, and retains conservative strict hit caps.
  Engine1824–1863 independently reconstructs all entry names, including empty
  files and non-Python configs. Raw metadata is cached separately from side
  projections; empty b'' remains present. Both mapped rename ends are covered.
- Helper238–256 checks compiler-reserved __debug__ binding positions. Ordinary
  binding231–235 refuses request/private and pytest/setup/teardown protocol
  prefixes; fixture names also refuse test*. The known special fixture-name
  failure is addressed in this source revision.
- Helper331 onward checks all repository conftests, including nonancestor
  hooks, plus relevant initializers/startup/config sources. Every collectable
  sibling must pass the same complete module grammar, without recursive proof
  or a filtered source projection supplied to another authority.
- The optional new proof requires callable read/search/path_lister. Missing or
  failing discovery cannot become known absence. No bound-method introspection
  supplies authority. Per-unit certificate consumption in oracle_credit165
  onward is still mandatory before the request whitelist can earn credit.

## B6 — case aliases / metadata authority: addressed at source level

GitSnapshot.read is exact; alias is a separate API (snapshot.py591–621).
The strict empty-needle search only enumerates nonempty lowercase .py sources
(snapshot.py624–640). Therefore that search alone could not establish absence
of Conftest.py, Conftest.PY or PYTEST.INI. D-158 is an explicit TASK root-fallback
contract, not a blanket exclusion of alias effects for every new oracle proof.
Installed pytest config/__init__.py705–707 constructs lowercase conftest.py and
calls Path.is_file, so a Windows checkout can open the differently spelled file.
This was source reasoning, not a native file-alias execution result.

The e13b helper now requires independent all-file metadata. _Paths68–116 rejects
duplicate/casefold-colliding file or directory names, opaque trailing slash
names, file ancestors, directory-as-file reads and alternate canonical config,
conftest, initializer or Python-extension spellings. Every _Reader128–151 read,
including a cache hit, checks that exact name against the metadata authority;
new callback values must agree with declared presence. All canonical Python
files, including empty ones, are read and cross-checked against nonempty search
hits at595–606. Missing search hits cannot be projected to inert modules.

The helper all-file cap is256; the engine metadata adapter has its own512 cap.
That difference is conservative refusal, not fake capability. D-158's stated
casefold/OS Unicode, 8.3 and other path-spelling residuals remain residuals;
this review does not claim full OS alias equivalence or cross-OS verification.

## Consumer projection / producer binding / budgets

Only all-file inventoried collectable consumers fully validated by _module are
excluded from certificate identities (153–161,615–624). Nonconsumer Python
sources, producer candidates, initializer/config reads and absence probes retain
their actual path/hash identities. The selected test filename, line number and
qualname are not certificate inputs. Full fixture AST remains in the existing
context; the extra certificate binds fixture shape, each call's complete
argument/default binding and read dependencies.

_definition rejects all producer imports/calls in this first domain and still
requires the existing whole-module primitive purity grammar. _bind completes
arity, duplicate/missing keyword and literal-default obligations. An empty
invocation set earns no per-unit certificate. Synthetic startup calls do not
substitute for real call bindings. The guard tail is only readonly bool/env
grammar, with no arbitrary request helper or inactive hidden yield bypass.

The helper caps are128 cached reads,64KiB/source,1MiB total,4096 AST nodes and
fewer than64 nonempty Python hits. Engine caches attempts across sides and has
its own256-key/2MiB budget. The first oversized callback payload may already
have been returned; it is charged and subsequent reads stop, not claimed unread.
Repository-visible .egg-info/.dist-info metadata anywhere in the all-file list
is refused. External installed plugin/import hooks remain an explicit model
boundary, not an assertion that they were empirically excluded.

## B7 — malformed bare parametrize sibling is still treated as closed

This is a new blocking source counterexample in e13b, NOT_EXECUTED. At223–228,
_bare_mark accepts bare @pytest.mark.parametrize because the attribute is a
nonprivate identifier. _module503–508 accepts that decorator on a plain sibling
with a closed assertion. At565–568 the marked sibling merely gets no certificate;
it does not invalidate the enclosing consumer module. Its module bytes are then
eligible for exclusion from identities. An unmarked test_total in that module
can still get a certificate even though pytest cannot finish collection there.

Primary installed pytest9.1.1 source, read without import or execution:

- mark/structures.py404–416: bare decorator stores a Mark with empty args.
- fixtures.py1663–1667: reads parametrize markers and calls
  ParameterSet._parse_parametrize_args(*marker.args, **marker.kwargs).
- mark/structures.py166–168: argnames and argvalues are required.
- python.py122–124 and1231–1234 independently consume the same required args.

The existing frontend does not discard this malformed bare decorator:
frontend.py3123–3128 only treats ast.Call decorators as parametrization rows,
leaving the plain unit to be collected statically. Thus this is not fixed by
param_cases being unknown. A before module with GATE+test_total and an after
module with the same GATE+test_total plus this sibling can pass the helper's
module grammar while after collection fails. No empirical final verdict escape
is claimed here; the admission proof itself is unsound for collection validity.

Minimal source shape is retained as bare-parametrize-sibling.py.txt. The narrow
repair is to refuse this bare built-in marker before certifying a module, with
an owned negative control. This does not require generic marker expansion.
Empty usefixtures is only a warning/no-effect in fixtures.py1842–1854;
filterwarnings with no args has no filter iteration; bare skip/skipif/xfail
have supported unconditional semantics. Those are not asserted to share B7.

## Owned reader test status

Only the authorized new test_inactive_fixture_context_reader.py was edited.
5f7de44 and fba5a242 copies are preserved under source-observations. The latest
2f1e07c7a89ceb93075b8e86e59d4b03af54a1f86533df492627803ff57390d2 adds the paired
truthful HEAD batch-reader capability after root's r2 capture exposed the
pre-existing mandatory paired-reader guard. Metadata fault/count behavior is
scoped to the optional recorder callback, never to the nth global call; other
mandatory consumers see the complete valid HEAD entry list and matching bytes.
The recorder grants no oracle credit. No product guard was weakened. This
reviewer ran no tests or collection and makes no green assertion for new bytes.
