# Inactive-fixture proof: independent read-only obligations

Status: PRE_IMPLEMENTATION_CHECKLIST, NOT_A_PASS. This reviewer has not run,
imported, compiled or tested product/prototype code. Original fbc and all prior
outputs are unchanged. New helper/integration source review is still pending.
HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL.

## Existing contracts that can be reused

| Source | What it actually proves / caller still owns |
|---|---|
| oracle_purity.py:150–195 | Source must be bytes≤65536 and AST≤4096. A pure module has inert/docstring statements, plain functions with literal defaults, no annotations/decorators/varargs/kwonly/posonly/generic types, or one narrowly recognized re import. This is a grammar, not a full runtime/binding certificate. |
| oracle_purity.py:198–207 | primitive_literal_result checks literal supplied args/keywords plus the module grammar. It does not bind the call to a complete signature, reject all wrong arity/unknown keyword/collision cases, or compare two different pure definitions. |
| oracle_purity.py:233–260,279–327 | A unique conventional-root local import leaf, regular-package/namespace precedence, inert selected ancestors and re-shadow checks. Caller must provide a strict side-specific read, exception/absence distinction, aggregate budget and complete binding/call set. |
| oracle_purity.py:263–276 | imported_from collects top-level absolute imports. It does not establish the final reaching binding after assignments, duplicate imports, function locals, monkeypatches or global mutation. |
| snapshot_context.py:104–185 | Strict inventory is required (fewer than64 nonempty source paths), siblings/startup/config discovery is bounded to128 selected paths; selected content≤100000B/4096 AST nodes. All discovered configs must admit only empty options or literal testpaths covering the unit. Unknown search/read/type/config/startup refuses proof. This helper is not the requested new128-path/64KiB/1MiB resolver contract by itself. |
| own_marks.py:78–137,289 onward | OwnMarks models module/class/decorator/param marks, mutation/plugin hooks and UNKNOWN. Supply the real full conftest-chain knowledge; an empty manually supplied marker list is not authority. Async/imported/custom/marked-param context can be UNKNOWN. |
| own_marks.py:157–198 | Exact get_closest_marker/get_marker of one literal name can be false only for known absent marks. Missing request.keywords membership/get is UNKNOWN, not false. Guard resolution dropping every outcome is not a proof that the complete fixture has no other effects. |
| setup_skip_controls.py:_fixture/_test_request | Existing fixture recognition is broader than this new certificate: it can accept aliases/name/options; _test_request only confirms function scope/request is not rebound. The new canonical predicate must independently reject extra options/dependencies/aliases/defaults/annotations/async/generator modes. |
| engine.py:1712–1757 / oracle_credit.py:81–178 | Existing startup, reflection and complete declaration/environment restrictions are independent obligations. Do not delete a module-wide request/reflection restriction merely because one fixture or one unit obtained a certificate. |

## Mandatory review checklist for the new API

1. **Side-bound reader:** the callback supplied to
   prove_inactive_fixtures(source,tree,functions,*,path,read) must resolve the
   selected BASE and HEAD independently. Changed/deleted/added/rename-old paths
   must consult the appropriate diff side before any unchanged root reader.
   A failure/oversize/nonregular source cannot masquerade as known absence.
   Cache keys must not borrow a HEAD value under a BASE path.
2. **Proof identity:** record canonical producer/import binding and every
   relevant source/config/initializer path plus hash, including an absence
   representation where discovery needs it. total()->78.75 and total()->0 are
   both pure in #571 but cannot yield the same equivalence certificate.
   Consumer test filename/lineno must not pollute a relocation certificate;
   actual resolved dependency paths/value obligations must remain bound.
3. **Resolver bounds:** at most128 distinct queried paths, max64KiB per source
   and1MiB total admitted source per defined proof invocation/side. Count
   absence/ambiguity/config/init probes too; use a shared bounded cache rather
   than resetting the budget per callee. Overflow/read failure returns unknown,
   with no partial certificate or retry through a different reader.
4. **No vacuity:** pure_imported_calls(source,[]) returns true by construction.
   Missing/empty discovered calls cannot certify an opaque producer or arbitrary
   module. Every relevant call must be classified; a genuinely call-free literal
   unit needs its own explicit closed domain rather than a guessed helper.
5. **Binding/arguments:** reject rebound/ambiguous producer and pytest names,
   local shadows, star imports, aliases not proven by the domain, dynamic
   imports/require, globals/locals/vars/frames and relevant namespace writes.
   Statically bind every positional/keyword/default argument to the selected
   signature; reject missing/extra/unknown/colliding args and * / **. Every
   supplied/default value must stay in the supported concrete literal domain.
6. **Framework/bootstrap:** prove canonical pytest fixture authority and its
   project shadow/initializer paths; no opaque import may mutate the decorator,
   request/marker machinery or producer binding. Read applicable ancestor
   conftests, initializers and pytest configurations for this side. Unknown
   plugin/config/startup scope withholds the new certificate. Retain the
   contract's external plugin/import-hook limitations; do not claim universal
   installed-environment equivalence.
7. **Exact fixture domain:** one canonical function-scoped autouse fixture,
   exactly the admitted request argument, no dependency/default/annotation,
   extra option/decorator/alias/async form. The first evaluated operand must be
   the exact literal marker read proven false for this unit. No prefix/suffix,
   nonempty else, yield/finalizer or indirect request use is covered.
   Reject Yield/YieldFrom even in an unreachable branch: Python would make the
   entire fixture a generator and pytest can fail because it did not yield.
8. **Same AST, exact nodes:** fixture/request IDs must belong to the exact AST
   from which the unit's oracle context is built. Do not replace that check with
   a broad spelling/span exception. Return per-qualname certificates; never
   union one unmarked test's allowed request nodes across all units, allowing a
   marked or UNKNOWN test to borrow its proof.
9. **Complete context:** retain the fixture's complete AST/decorator/body in
   the proof even when inactive. Keep all unrelated imports, helpers, defaults,
   class/receiver/setup/identity and assertion contexts. Preserve ordinary
   admission, liveness, freeze, detector results and once-only spend semantics.
   Missing/malformed/empty certificates remain unknown; no new exemption.

## Focused source-level negative witnesses to check (NOT_EXECUTED)

- Before/after pure total definitions return different literals: purity true
  on each side must still produce different proof identities.
- HEAD adds/deletes/renames a producer, initializer or pytest config: BASE
  cannot borrow the HEAD path's bytes or known absence.
- Imported total is later reassigned, shadowed locally or called with missing,
  duplicate or unknown keyword arguments; empty call discovery is not proof.
- Two units share one fixture: unmarked known unit versus marked/UNKNOWN unit;
  only the former may receive the inactive certificate.
- scope=module/class/session, fixture params/name/extra decorator, request
  rebinding or hidden yield, plugin/addopts/pytest_plugins and package shadow
  all retain unknown or the original refusal.
- 129th source probe, source65537B, total source above1MiB, wrong return type,
  refused read or ambiguity must not leave a partially usable certificate.

The original #571 stored helper/OwnMarks observations are read as historical
subproof evidence only. No new observation is generated by this checklist and
no prototype is approved before its actual helper plus engine/oracle wiring
has received source-level review.
