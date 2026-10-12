# JS/TS synchronous assertion swallowing (#363)

The frontend supplies `BROAD_EXCEPT_ADDED` evidence when a new same-function
try/catch surrounds an already represented synchronous assertion and its
catch neither directly rethrows nor reaches a resolved assertion. Empty,
comment-only, return and log-and-continue catches are covered. The engine
compares the evidence as a multiset before and after; adding suppression or
removing a preserving rethrow can therefore report the existing rule.

This uses the existing bounded token, binding and assertion model. It does
not add a JavaScript parser, run target code, change severity, or give JS
production code repair credit. Catch binding renames, comments and spacing
do not change the evidence key. Equal-count replacement of one swallowing
site with another is a residual of the multiset comparison.

The synchronous channel excludes promise-completion assertions by their
resolved API and actual call chain, including Node, AVA and tap async methods.
Operands and literal strings containing `.resolves` or `.rejects` do not
change that classification. Cross-function propagation, awaited expressions,
unknown conditional control flow, loop/switch/with structure, nested try
effects, class evaluation, labeled statements, typed function declaration
headers and `finally` are outside scope. Literal true/false branches and
direct terminal statements are read from the owning function body so a
try proved dead within that owning body supplies no evidence. Parent
callback registration/invocation reachability is not propagated: inline
callback obligations remain lexical, as in the existing frontend. Traversal stops at 32 structural
levels and supplies no claim for deeper shapes. An unused nested function cannot donate its
throw or assertion as catch safety. Supported assertion recognition retains
the existing import and lexical-shadow rules.

Represented Chai should getters use their actual chain anchor, including
property, parenthesized and indexed subjects. An assertion shape whose
completion cannot be classified makes its handler unsupported; it is never
silently removed from catch safety while claiming the catch is supported.

Assertion and unsupported-operator positions are indexed per function owner;
outer callback statements do not rescan descendant function tokens. Deep
input safety and callback-size scaling have new remote regression proposals.
No performance measurement has been executed on the work machine.

New fixture labels and the precise capability text are review proposals
until accepted under the maintainer's preparation authorization. Existing
fixture expected outputs and protected policy/gate files are unchanged.

The pre-fix remote reproduction is source
`b29cb836a4e2ddc241f737bc71e2720dffd749a8`, run `38087693144`, attempt 1:
13 failing new expectations and 133 passing controls, zero errors/skips.
The raw failure and source-bound artifact are retained. This is a named
defect reproduction, not a population false-positive or detection-rate
measurement. New implementation heads require their own remote results.
