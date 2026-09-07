# Numeric assertion restoration (v0.3.0)

v0.3.0 can recognize a narrow strengthening such as
`assert add(2, 3) > 0` becoming `assert add(2, 3) == 5`. The new exact numeric
value must satisfy the old bound, the subject must be structurally identical,
and the surrounding source must be proven unchanged. `> 0` becoming `== -1`,
an ordinary exact-value rewrite, or an assertion weakening still produces its
existing finding.

The source proof is deliberately small. The diff must contain exactly one
non-artifact file change, without a rename. The engine compares the two
frontend-normalized snapshots outside native bare `assert` statements and
allows at most one of those statements to change. Other assertions, imports,
function bodies, module constants, defaults, indentation, and comments must
remain identical. The normalizer is the same one that supplies frontend spans:
UTF-8 BOM handling and line-ending normalization; other whitespace is retained.

Changing another file, even documentation, conservatively retains the original
finding. So does strengthening several assertions together. This avoids
assuming that an imported callee, test input, or side effect stayed the same.
It does not alter the existing severity, repair-evidence, or fail-on policy.

The optional IR field `FileIR.native_assertion_context_unchanged` carries this
proof and defaults to `false`. It is computed from validated native spans
before cross-file or helper assertions are inherited. Missing, overlapping or
unverified spans decline the proof. Inherited assertions and entire
`pytest.raises` blocks are never masked as native bare assertions. Direct IR
producers that cannot provide the proof keep the original finding.

This remains a static rule for ordinary numeric comparisons. It does not
execute code or prove purity or the behavior of overloaded operators. The
candidate's broader corpus and release qualification are separate from these
focused controls; this page does not claim a new benchmark result.
