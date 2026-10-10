# Unadopted reference input repair

The original v0.6.0 artifact can emit a normal pass when a required changed test
blob is missing or corrupt. This separate source proposal backports the named
Git input failure repair onto exact8c70efb, without changing detectors, rules,
gates, existing fixture expectations, or the version/release identity.

Unlike the newer candidate, this source retains the original snapshot inventory
refusal for submodules. It does not import the newer opaque-submodule behavior.
Requiring a full inventory can also reject inputs formerly read through a single
permissive callback; these are explicit input failures, not false-positive fixes.
All bounds/refusals remain ENGINE_FAILURE in the full measurement denominator.
Worktree capture is still non-atomic; post-capture limits are not memory caps.

Remote preparation covers the inherited113 Git input cases (including normal
controls and two added original-submodule refusal checks), the original strict
snapshot/CLI contracts and byte parity over the unchanged original synthetic
corpus. Counts and failures must be read from receipts. This is not a historical
cost run or a held-out sample. Neither these tests nor a new head silently
replace the original reference artifact. Artifact delivery, independent source
review, full qualification, prospective comparator disposition, cost/method
freeze and applicable execution approval remain separate gates. No release,
tag, product-main merge, or downstream repin is requested by this branch.
