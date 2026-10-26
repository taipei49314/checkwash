# Future bounded controls — all NOT_EXECUTED in this packet

Expected outcomes below are proposal requirements, not observed results. Run on
the new source only after implementing/reviewing the predicates. Keep original
test expectations and existing golden labels unchanged. Compare default and
oracle_freeze; retain fail_on warn/high/critical semantics rather than forcing
all exits to BLOCK when the configured threshold deliberately permits high.

## #263 passive-class controls

Positive requirements:
- exact original two functions → exact original class fixture, with explicit
  closed root context; preserve original PASS and no-high assertions;
- same move without any class mark; and the existing plain rename/move/unroll
  controls remain valid under the strict startup context;
- receiver is an unused ordinary self, not data supplied by a fixture.

Refuse optional credit (ordinary detectors/severity remain responsible):
1. original helper with no root reader; unreadable/unknown root startup;
2. active `skipif('sys.platform == "win32"')`, always true mark, invalid string,
   strict xfail, unknown/custom marker or side-effecting condition;
3. same alias rebound, used by any other helper/body/default, assigned under an
   if, imported/shadowed pytest/sys, mutated pytest.mark or aliased decorator;
4. class base/metaclass/decorator, __init__/__new__, setup_method/setup_class,
   autouse fixture/class helper/descriptor or any other class state;
5. self/cls read, modified receiver default/annotation, staticmethod/classmethod,
   property, callback/fixture args or generic syntax;
6. inherited marks, request.keywords/class-name skip, plugin/config hook that
   changes marks, differing nonempty package initializer/conftest chains;
7. changed expected literal/body, reordered side-effecting assertions, changed
   module binding/import producer, module/helper __name__/__file__/reflection;
8. two old units to one arrival: cannot spend one proof twice.
9. a supplied producer module mutates pytest.mark.skipif before the newly
   introduced marker-binding call; unchanged import spelling is not sufficient
   framework authority. Opaque startup/dependency authority retains unknown.
10. an unchanged imported add/helper observes caller frame locals (including
    self), receiver identity or co_qualname/class via an opaque observer. A
    selected body's unused receiver is insufficient; missing closed callee
    implementation/call-effect proof must retain UNKNOWN. This control is a
    future requirement, not a newly executed Python observation.

## #358 inactive-fixture controls

Positive requirements:
- exact original GATE in both modules, plain unmarked parameterless test,
  strict APP+test snapshot: preserve original PASS/no-high expectation;
- no-GATE pure move as independent existing-mechanism control;
- explicit literal scope='function' may be admitted only with the same complete
  predicate, not by treating all fixture scopes as request-to-test scope.

Refuse optional credit:
1. slow mark present, marks UNKNOWN, conftest/plugin/config collection injection;
2. inverted guard, literal true guard, unknown first operand, dynamic mark name,
   request.keywords/path/name/nodeid reads or request reassignment;
3. call/mutation/assignment before or after the If, nonempty else, yield/return
   value/finalizer/teardown, request/body dependency, another autouse fixture;
4. module/class/session scope, custom fixture decorator, extra fixture options,
   helper parameters/defaults/annotations, decorated/imported callback;
5. selected test itself takes/reads request, method/class wrapper or additional
   requested fixture not covered by the initial domain;
6. changed fixture bytes, startup/package initializer/provenance difference or
   body/global binding/expected-value difference;
7. per-module caching that uses an unmarked unit's proof for a marked sibling;
8. marked sibling is blocked while the unmarked unit remains independently
   eligible; neither can purchase another disappearing unit's oracle twice.

Retain all six previously demonstrated D179 counterexample families: prior
assertion side effects, builtin/getattr mutation including imported bootstrap,
bare relative side-effect imports, package initializers, helper module identity,
and one-arrival/multiple-removal spending. No optional getattr projection is
reintroduced. These requirements deliberately preserve conservative costs
outside the two narrow proof domains.
