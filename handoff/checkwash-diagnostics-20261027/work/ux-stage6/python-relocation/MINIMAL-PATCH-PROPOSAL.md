# Minimal product change specification (inert, not an apply-ready patch)

Status: PROPOSED / NOT_IMPLEMENTED / NOT_EXECUTED. This file describes exact
source insertion points and helper contracts. It intentionally contains no
dummy helper returning true and is not a git-apply candidate. A generic removal
of class_name, self, request, fixture decorators or environment statements is
rejected. No product, test expectation, gate or protected file was edited.

## Named defect A: inactive function-scoped fixture blocks a plain move

Product file: `src/checkwash/oracle_credit.py` only, unless review identifies
missing startup provenance that requires explicit engine plumbing.

1. Preserve all existing forbidden names/attributes except split `request` into
   a separate post-selection guard. Before accepting any request occurrence,
   identify its enclosing non-selected module-level fixture and the selected
   target unit. A Name(request) outside the positively proven fixture stays a
   rejection. The selected test itself still cannot take/read request.
2. New internal helper `inactive_fixture_for_unit(tree, fixture, function)`
   returns a proof only for the following complete predicate:
   - unique unshadowed `import pytest`, exact plain @pytest.fixture(autouse=True)
     with absent scope or literal scope='function'; no extra options, aliases,
     custom decorators, parameterization, async form or requested dependencies;
   - one plain argument request, no annotations/defaults/rebinding/varargs;
   - fixture body contains exactly one If, no nonempty else, no yield/finalizer,
     prefix or suffix; only permitted request load is the first Boolean-And
     operand's exact request.node.get_closest_marker('literal_name') call;
   - OwnMarks.of(function) is known and lacks that literal mark. No heuristic
     based on side.markers == [] can stand in for complete mark knowledge;
   - the engine-supplied strict startup context is known and excludes conftest
     or configuration mark injection. Do not invoke OwnMarks without preserving
     that provenance. Restrict the initial domain to plain parameterless tests
     with no decorators and no other fixture definitions/dependencies.
3. context_statements may admit that one helper's fixture decorator. Preserve
   its entire AST/decorator/body in the environment key. No arbitrary decorated
   helper is admitted. Admit only the verified request Name ids; all other
   reflection restrictions and function/unit bounds remain unchanged.
4. A proof is per target unit. A marked/unknown unit in the same module cannot
   borrow the unmarked unit's result. Use an explicit projection-domain tag
   in the proof key when the new path is used. Do not silently label it as a
   proof obtained without the new obligation.

This admits the #358 no-effect fixture without restoring a general request
identity waiver. The retained full helper AST means changing its body/decorator
does not accidentally compare equal even if the new path is inactive.

## Named defect B: passive class wrapper with an always-inactive mark

Caller-only prerequisite proposal (no expected assertions change): the existing
#263 outcome helper supplies a strict closed HEAD snapshot, with in-diff BASE
bytes still supplied by FileChange.before. Do not synthesize closed context in
the engine when a caller omitted root_reader.

Product insertion points: before context_statements in _python_context, and
declaration/args/class_name construction currently around :177-205.

1. A new passive-class predicate requires: no bases, keywords, decorators,
   constructor/setup/helper methods/class variables; all nontrivial body nodes
   are selected test methods plus at most the admitted pytestmark. The test
   methods are ordinary def methods with a single leading unused self receiver,
   no annotation/default/decorator or other fixture/callback input.
2. For the initial domain, a class pytestmark is either absent or a sole alias
   bound exactly once to pytest.mark.skipif('pure_version_comparison'). The alias
   has no other loads/writes. Pytest is uniquely imported as pytest, and sys is
   not rebound in the module. The pure condition is a single comparison of
   sys.version_info against a literal integer tuple; no calls, unknown names,
   attribute indirection, custom comparisons or side-effecting subexpressions.
   It must be false for every environment in the existing D6 matrix, not merely
   accepted as a compat gate or live somewhere.
3. Remove only those positively identified no-effect marker bindings/class
   wrapper shells from the canonical environment. Strip only the proven unused
   leading receiver from a cloned args and cloned declaration; never mutate the
   frontend IR or source AST. The body/assertions, other defaults/decorators,
   parameter rows, order, imports, module bindings and startup remain exact.
   A spelling-only `import pytest` check is insufficient authority: an opaque
   earlier producer import may mutate pytest.mark.skipif, just as imported
   bootstrap code can mutate a builtin. Reject project pytest shadow modules,
   relevant namespace mutation and opaque startup imports that could affect the
   new call. Require a bounded known-pure producer/startup context or retain
   unknown. The existing263 closed-root arm supplies only the test module; it
   does not by itself discharge this stronger framework-call obligation.
4. Retain class_name/args as today for every class outside this proof domain.
   Reject instance/class access, inheritance, descriptors, class construction
   effects, class fixture/setup scopes and reflection. Use a projection-domain
   tag for both equivalent top-level and proven-passive-class units so they can
   match; do not make an unknown class hash equal to a plain function by default.
   **Unresolved prerequisite:** an unused receiver in the selected AST does not
   prove an imported callee ignores the caller's receiver, frame locals,
   class/qualname or other context. Require explicit bounded call-effect and
   identity closure for relevant imports/callees; otherwise keep UNKNOWN.
   Original263 does not provide app.calc.add's closed implementation. Its
   current API fixture, even with the diagnostic's test-only closed-root map,
   therefore does not establish that obligation and must not be predicted PASS.
   The rejected JS opaque-observer prototype is a caution, not proof that a
   Python class/unused-self projection is safe. No blanket normalization follows.
5. Preserve liveness and every detector. A surviving arrival still must be live;
   multiset spending remains once-only. Do not change E2/fail_on severity or
   broaden D2/D5 to text/mass. Internal new proof paths keep IR3 field types
   unchanged, but any adoption must explicitly review the D179 contract wording.

## Required adoption order

1. Implement helper logic outside the frozen fbc tree, preserving this draft.
2. Independent adversarial review of all failure predicates and mark/startup
   authority; add the controls in NEGATIVE-CONTROLS without changing old labels.
3. Record red/current and green/new-source API/CLI observations with working-tree
   hashes; no claimed fixture execution and no modified judge on old receipts.
4. Run the targeted original positives, the full D179 counterexamples and ordinary
   controls, then complete gates/qualification on the new sealed source. Preserve
   every remaining failure. A passing pair of positives is not general acceptance.

No product patch has been applied or executed by this packet.
