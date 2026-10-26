# Decision log

Entries D-001 to D-140, everything up to and including the v0.8.0 release
entry, are in [DECISIONS-archive-1.md](DECISIONS-archive-1.md). They moved
there unchanged on 2026-10-20, when this file had passed 1,000,000 bytes,
checkwash's source byte limit, above which it sets a documentation file
aside unread (F40). The archive keeps the line numbers they had here: read
against `94953c83`, the last commit before the move, a reference
`DECISIONS.md:N` with N up to 10833 is `DECISIONS-archive-1.md:N`. Any
other line reference written before the move reads against that commit.
Entry numbers do not change, and new entries are added here.

Entries D-141 to D-172 moved unchanged at v0.9.0 publication to [DECISIONS-archive-2.md](DECISIONS-archive-2.md), except its prescribed archive title and single-line provenance; old line references read against release commit d6eda4f6.

## D-173 (2026-10-23): post-publication verdict baseline v0.9.0, separate from advertised pins

After approving the real PyPI deployment, Nelson instructed this chat:
「PyPI 已核准，照既有 G4 繼續，把 v0.9.0 的公開產物驗證、pins 更新和 baseline rotation 做完。」
The existing G4 grant explicitly includes the separate rotation PR while
retaining his disposition of protected changes. This entry records that
bounded continuation and its metadata bookkeeping, not a new case ruling or
standing authority for another release.

The baseline becomes public v0.9.0, version 0.9.0, release commit
`d6eda4f695fabb8e7d138f7a87b099d2028f0294`. Its actual Release pyz is
914407 bytes, SHA256
`7319152cdf4889df4d58b454dc63072bb2e923823e1b2ce09677e4381dbccd5c`,
independently downloaded and verified by hosted run `39821892775/1` after
human-approved release run `39817071157/1` completed successfully.

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
baseline header and explanatory comment from v0.8.0 to v0.9.0. It has no
`[[accept]]` entries; none is added, retired or re-adjudicated. Existing case
labels, fixture expectations and the rule that a still-passing block-labelled
case needs acceptance remain unchanged. A future stale entry can be removed
only when specifically named by a rotation receipt and covered by its ruling.

Tag verdict `39811579829/1` ran 185 cases with zero failures/reported moves,
159 block-to-block and 26 pass-to-pass against v0.8.0. It proposed no changed
blocked/T3 pin; the chai input blob is unchanged. Thus `baseline_blocked`
stays 159 / `9993cab624a6ee1831a27f33fb48088676a639e9f5dd2a1b69361f1048c3f3a4`
and the 26-case T3 map stays. Canary v0.4.2 to v0.5.0 and its 71 known
block-to-pass IDs are not rotated.

Acceptance of this configuration still requires this independent rotation
PR's fresh hosted verdict against the actual public v0.9.0 pyz, with full
185-case coverage and no baseline/member/pin/acceptance drift, plus its other
required checks. Earlier tag receipts are the proposal basis, not a substitute
for that run. Native PR/main results and exact identities are retained with
the closeout evidence. No local product execution, public tag change or
downstream re-pin is part of this rotation.

## D-174 (2026-10-23): measured keyword-operand acceptance, addendum to D-143 (#462)

Nelson approved the concrete D-143 addendum in PR #558 and its conditional
merge/issue closeout in this chat on 2026-10-23:
「核可草稿，檢查通過後合併並結案（建議）」.
This was an assistant-written reply option. The approval covers this
wording and merging #558 after its current CI/dogfood gates pass, then
closing #345 and #462. It grants no new workload execution or publication.

The frozen combined sweep measured a418 (`717a705d5291913cea98544ffd57b191e0d07a88`)
to a462 (`2422b3cebcebdb4cbf25ca0d567589d8bb6b540e`) on 3,018 members:
2,599 pass→pass, 400 block→block and 19 error→error, with no outcome,
finding or stdout differences. The kw462 selection has two members,
both pass→pass, with no new finding. Both requested difference lists
are empty; the selection is nonempty. This supplies D-143's subsequent
measurement under R2–R7 and keeps its original preparation record
unchanged. Provenance is human-authorized local PJU, NOT EC pool,
under the previously approved frozen declaration. This does not
establish a general false-positive rate or resolve the named syntax
residuals.

Sources: [frozen combined sweep](https://github.com/taipei49314/checkwash-lab/blob/92d771e2bfb41b1109b57cce55f3df2a0e99726d/evidence/v090-sweep-results-20261022.md);
[exact pair/engine/count extract](docs/releases/v0.9.0-issue-closeout.json);
[issue result and remaining gate](https://github.com/taipei49314/checkwash/issues/462#issuecomment-6360716240).
The source combined JSON SHA256 is
`b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`.
D-143 in DECISIONS-archive-2.md remains unchanged as its dated preparation
record. This later addendum records the approved measurement without
relabeling those old arms as a fresh rcprime run.

## D-175 (2026-10-23): measured class-decorator acceptance, addendum to D-149 (#487)

Nelson approved the [concrete D-149 measurement draft](https://github.com/taipei49314/checkwash/issues/487#issuecomment-6360870539) in this chat on 2026-10-23 by selecting 「核可補記，檢查通過後合併並結案（建議）」, an assistant-written option. The scope is this measurement text, merge after current CI/dogfood passes, and closure of #487. It grants no new workload execution, publication, expanded decorator support or log-capture equivalence ruling.

The frozen a429b (`f4b65db6d33cecb5fc460a43aff2ad881764aa61`) to a487 (`637222e8cffd8f5fbfa0aa0502852a139af78f22`) pair completed all 4,818 declared members across standard, D-088 and the extension/JavaScript sets. Outcomes: 4,355 PASS→PASS, 440 BLOCK→BLOCK, two BLOCK→PASS and 21 unchanged product errors. Nine rows have finding/stdout differences; the errors are not passes.

All seven D-149 watch commits match its expected effects. `c8aa429c9b` returns to PASS with four warn findings; `e058a05763` returns to PASS with six TEST_DISABLED warn findings. `14737e91ed`, `36c3c9713e`, `c5b1ee8101` and `c76190d491` stay BLOCK without the 37 added ASSERT_REMOVED. `02ed71d887` stays BLOCK without the extra ASSERT_SUBSTITUTED high, retaining its 71 TEST_DISABLED high and separate ASSERT_WEAKENED high.

The two additional BLOCK→BLOCK rows have been reported and source-reviewed. On scrapy `6b2997af`, 30 newly exposed ASSERT_REMOVED/high findings are assertions still present in two still-called helpers that become static methods; four EXPECTATION_DEFINITION_CHANGED/high findings keep the same response-request equality while the requested URL moves from setup state to a fixture argument. One ASSERT_WEAKENED/high finding keeps an exact warning-match count of one but changes the log-capture API; full capture equivalence remains unverified. On scrapy `b4d11b8b`, four newly exposed ASSERT_REMOVED/high findings are unchanged URL guards reached through test methods newly carrying a coroutine-to-Deferred decorator. These expose helper-reading and existing-detector boundaries; they are neither new blocked commits nor 39 adjudicated true positives.

This supplies D-149's later measurement and report-other-changes condition without broadening its supported decorators, changing existing fixture expectations, or adjudicating the remaining log-capture equivalence. It establishes no general false-positive rate. The archived D-149 preparation entry stays unchanged. Provenance is existing human-authorized local PJU, NOT EC pool; no new execution occurred. The whole combined manifest remains incomplete because of separately stopped/deferred arms; this pair is complete under R2/R3/R6/R7.

Sources: [frozen combined sweep](https://github.com/taipei49314/checkwash-lab/blob/92d771e2bfb41b1109b57cce55f3df2a0e99726d/evidence/v090-sweep-results-20261022.md), [exact pair extraction in #558](https://github.com/taipei49314/checkwash/blob/c991936d0f283db3b265a2065af0ca99d825de9b/docs/releases/v0.9.0-issue-closeout.json). The source combined JSON SHA256 is `b9946817dacdcbd9ebec052e0910e1e2e30aa7dd0dc3e0e04e145d6d68e9e2db`.

## D-176 (2026-10-23): first-stage Python unit-less broad-except candidate (#419)

Nelson selected 「核可第一階段開發與 PJU 驗證（建議）」 in this chat.
That is the verbatim assistant-written reply option, not a quotation of a
longer human-authored ruling. It accepts the r1 packet's first-stage scope:
apply its narrow implementation and protected-text drafts, complete the
new tests and validate on PJU, stopping for any existing-expectation or
out-of-scope outcome movement. The approved packet's manifest SHA256 is
`fc2db8f745637d124a2e7a11f2a68fe0a4c7d264700eae70708cfc048771aea0`,
based on engine source `618c415d9d3d37f004142edcaed331057ea8ac0f`.
The isolated development branch starts at
`e10cddcd9668d81baef64d18ab591dae5f8f5cd7`, whose engine is unchanged from
that packet's baseline. D-141 and D-171 remain unchanged in their archive.

D-171's broad opaque refusal remains off: `OPAQUE_REFUSED_RULES` stays
empty. The only separate refusal requires `BROAD_EXCEPT_ADDED`, the
finding's own `f.unit is None`, a resolved `unit is None`, a Python
`FileIR`, and the existing `judged_as_test(file)` or conftest role.
A nonempty unit name that misses lookup is not a unit-less finding.
`judged_as_test` includes retained roles carrying test obligations, not
only role `test` or a literal `tests/` directory. Production-role handlers
without test obligations do not join the oracle path.

The current detector records every broad-except finding without a unit.
Thus this gate does not further divide today's findings by syntax or
position: it also covers recognised handlers inside functions, and does
not mean module-top-level `except Exception: pass` only. A sibling unit's
symbol evidence does not reach a file-scoped finding. Without another
valid de-escalator, refusal reaches existing E1/high; when opaque production
changed, the label is `OPAQUE_PROD_CHANGE_NOT_EVIDENCE`. A suite control
keeps its earlier reason. Severity thresholds, compensation order, E2,
base-side allowances, fingerprints, detector syntax and unit pairing do
not change. Python weakening/removal/disabling/tolerance rules and JS/TS
keep D-171's current credit behavior.

Comment-only and substantive opaque implementation modifications lose the
same credit. That is a development-stage blocking risk, not proof that
the production edit is irrelevant or dishonest. The new C source-data
example tests the mechanism; it is not a runtime-qualified honest repair
or an adjudicated false positive. Historical cost has not been measured or
accepted for this candidate.

The new unit/engine and golden tests encode expectations for Python refusal, conftest and
retained-role boundaries, unchanged production/JS/TS behavior, all four
other former-refusal rules, the unresolved nonempty-unit boundary, and E2.
A new CLI test is written to verify head-only allowance rejection and active base-side
allowance precedence over E2, in worktree and committed-range modes.
Existing fixture expectations and `tests/gates/**` are not edited; the
deleted D-141 five-rule suite is not restored.

The first-stage execution scope is development tests, source/wheel/pyz
qualification and published pinned/candidate Action dogfood on
LAPTOP-01AGNPJU. Keep exact source/base/tree, runtime, commands, raw exits
and receipts, with `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. Missing
platforms stay NOT_RUN. If an existing expectation or a finding/verdict
outside this scope moves, retain the failure and stop for the exact
difference; do not change a label, gate, threshold or allowlist to pass.
Protected document edits may themselves trigger critical dogfood findings;
this approval does not waive those checks.

**Preparation status: NOT_RUN.** This entry records source changes and the
development authorization; no candidate test, qualification, dogfood,
historical replay or sweep result has yet been observed in this stage.
It grants no merge, publication, issue closure or historical workload.
A later historical-cost packet must freeze baseline/candidate and Lab SHAs,
complete membership/hash, commands/attempts/deadlines, failure retention
and acceptance terms. Old D-141 arms and consumed sweep grants do not revive.

The eleven historical stop commits' high findings are not broad-except
findings. Werkzeug `ab6150fa` also has four broad-except warn findings in
`examples/couchy/{application,models}.py` and
`examples/cupoftee/{db,network}.py`; their production role is why unchanged
behavior is predicted. None of this is a candidate replay or a zero-cost
measurement. Route A, other Python Route B and file-scoped credits, JS/TS
(#212), and unrecognised neutralisation syntax remain. #419 and THREATMODEL
rows 2, 93, 130 and 131 remain open.


## D-177 (2026-10-27): compare newly winning policy files with effective BASE policy

Nelson instructed this repair continuation: 「我覺得可以一次做完吧 可以推版號 但到1.0版前要停下問我」.
Under that instruction this named defect, its necessary protected contract
and consumer migrations are implemented for the 0.10.0 working-tree candidate.
The pre-1.0 scope supersedes the earlier UX-only/inert boundary; 1.0 still
requires Nelson's decision. It does not rewrite old v0.9.1 tags or failed,
partial and consumed receipts, nor waive validation or publication gates.

Previously, per-filename config/allow lookup already selected `.checkwash/`
over `.greenwash/`, but guardrail classification compared a new physical path
with its own absence. Defaults comparison missed a legacy block-on-parse-error
policy shadowed by a pass-with-warning priority config; it also blocked equal
or tighter copies of already-disabled policies. New priority ledgers were
compared with an empty ledger even when they displaced an effective legacy
ledger. The earlier source-bound PJU observations and inert packet remain
historical evidence, not validation of this implementation.

The adopted §6 rule compares only a newly winning priority creation with its
existing selected legacy BASE predecessor. Equal roles, a subset disable set,
no threshold rise and no engine-error weakening establish nonweakening. Other
recognized relaxation or an uncomparable policy stays critical. Effective
ledger prefix additions retain EXEMPTION_ADDED for the true suffix; equality
adds nothing, and rewrite/revocation stays critical. Authority during the
reviewed diff still comes from BASE, with config and allow selected separately.

Selected BASE provenance is explicit and content-bound. The engine's lexical
slash normalization applies before policy classification and to mapping/case
keys. Ambiguous or HEAD-only context stays unknown per filename, with refusal
only when its new priority creation needs that proof; unrelated cases retain
their admission. No HEAD ledger becomes an active fixture exemption.

This changes frozen policy interpretation and shadow GUARDRAIL fingerprints,
so the candidate is 0.10.0. The required globals.policy_shadows proof slot is
present even when empty and advances IR to 3; findings remains 2. Historical
IR2 stays unchanged and gains no inferred proof. Current-source corpus
validation requires IR3; the historical comparator retains raw IR2 and every
typed version/key/behavior delta. Existing shadow approvals need review, never
mechanical translation. Existing golden/corpus expected labels are untouched.

Conservative costs remain for differing role tables, warning-bearing configs,
ledger revocation and unsupported copy-plus-delete/Git-rename maintenance.
Inactive-file costs, ignored invalid allow records, multi-ledger attribution
and BASE role overrides remain separate limitations. This decision changes
neither general engine-error behavior nor unrelated oracle semantics.

Targeted policy/API/IR3 regression and native comparisons are being recorded
on actual PJU working-tree hashes. Validation, integration, acceptance and
publication remain distinct; this entry claims no missing platform, full-suite,
source/wheel/pyz or release-collector PASS. Required checks remain pending until
their own final-source receipts exist.

## D-178 (2026-10-27): TASK lookup belongs to the original repo address

Bind `--task` once to the original `--repo` directory, using native lexical
join/abspath and retaining `args.repo_given` before Git re-rooting. The old
code passed a raw relative task token to relpath/open, so cwd could choose a
different existing BASE contract; this caused both PASS-instead-of-freeze
and BLOCK-against-the-wrong-contract, not merely lookup errors. The lookup,
root-only genuine-absence fallback and context diagnostic now use the same
T. BASE authority, #416's nonroot miss refusal and #500's case/prefix alias
refusal remain. No HEAD realpath is used to determine authority.

This is a minor contract change even when it corrects the previous SPEC
sentence: actual scope/freeze selection can change both verdict directions
and SCOPE_DRIFT identity. Existing callers relying on cwd-relative behavior
must express a path relative to the intended `--repo` directory, or use a
fully-qualified repository-owned task address. Native Windows rooted/drive-
relative behavior is explicit; untested UNC/cross-volume forms must remain
NOT_RUN rather than inheriting a blanket compatibility claim.

Historical 9a observations, forecasts and their corrected raw-vs-LF metadata
remain preserved. Current development receipts identify their own copied
working-tree bytes and do not claim that HEAD already contains those edits.
Native range/worktree controls compare the same intended BASE contract;
the fixture source itself is never executed. Root records final accepted
source and validation separately. D-178 does not authorize a 1.0 release or
revive historical/paid/model/adjudication grants.

## D-180 (2026-10-27): retain prior-BASE quality maintenance review

Quality policy and exemption maintenance retains prior-BASE authority and
the two existing trust lanes. Main `check` continues to classify an edit of
an existing `.checkwash/quality-allow.toml` as GUARDRAIL_TOUCHED/critical.
Quality continues to report a schema-valid append at warn and evaluates
only eligible BASE entries. A new HEAD entry cannot excuse that same
comparison. A quality `reported` result with exit 0 is not a clean result,
does not replace main `check`, and does not establish that main's required
check passed. Each required lane must run against its intended range.

The concrete second-entry friction is deliberately retained: the preserved
18 native controls show append-only report and enforce comparisons with
main BLOCK/1 versus quality reported/0. An existing exact eligible BASE
entry still works. Expired or wrong-target entries do not match; unknown
or malformed quality policy is a hard error. Those observations establish
the lane distinction, not a natural-repository false-positive rate or human
review acceptance of the synthetic fixtures.

The maintenance route remains exact prior review. Capture the intended q1
quality identity and main GUARDRAIL_TOUCHED v2 identity; use the existing
maintainer/BASE review process. If that process uses the main exemption
route, its exact main GUARDRAIL key must already be in a separately accepted
BASE. QW keys never belong in the main ledger. Commit presence alone is
not evidence of human approval. No blanket `quality*` exclusion, broad
"tightening" exemption, generator/ownership self-claim or HEAD self-approval
is introduced. No exemption is added to make this PR pass.

This decision changes protected documentation only, preserving the existing
main and quality executable gate behavior, findings schema, fingerprints,
exit meanings, writers and authority. Initial-creation rules remain their
own contract; D-177's separately bounded main config/allow shadow handling
does not extend to these quality paths. Release/publication acceptance and
the human's pre-1.0 stop remain independent requirements.

## D-181 (2026-10-27): validate TASK authority before applying its subset

Nelson's pre-1.0 repair continuation authorizes the necessary core contracts
and version movement. The previous UX stage only warned about unsupported
TASK syntax; a commented or quoted true, BOM or flow list could still silently
disable intended freeze/scope. 0.10.0 authority loading now refuses those
recognized unsupported or ambiguous inputs with EngineError before analysis.
The restricted block language is retained, without a YAML runtime dependency.

`load_contract` validates complete input before decoding. Duplicate/unknown or
misnested policy fields refuse as well. Canonical/legacy headers, true/false,
quoted literal globs, unrelated metadata, absent policy and the existing empty
scope meaning are controlled. Historical `parse_contract` decoding remains for
old static case records; it is not an authority loader. The old CLI syntax
regression now asserts refusal and no partial verdict instead of its superseded
advisory-only result; no golden fixture expectation is changed.

This is a deliberate minor-version CLI policy compatibility cost. Existing
unsupported TASK files need canonical rewriting after review. Error projection
retains exit 2 and the hook's non-blocking NOT_ANALYSED message; no fake clean
result, guessed YAML coercion or automatic activation is introduced. Targeted
and final-source checks must identify their own input hashes and actual runs.

## D-182 (2026-10-27): CRLF checkout text may preserve worktree relocation identity

The worktree reader previously paired delete/add only by raw equality, while
Git can store LF and check out CRLF. Identical textual relocation could lose
its identity before analysis. Under the same core-repair instruction, 0.10.0
allows exact UTF-8 CRLF/LF equivalence only during pairing, retaining original
source bytes. No lossy decode, whitespace/similarity matching, lone-CR folding
or reader-admission change is made. NUL/invalid UTF-8 use raw equality.

Deterministic tie ordering and one-use matching remain. New controls include
native staged/untracked CRLF relocation with adjacent weakening and complete
range/worktree finding comparison, plus content/whitespace/binary/invalid-UTF-8
negatives. This closes that bounded EOL discrepancy; other native Git
similarity, parameter and oracle-credit differences are not declared solved
by the reader change. Existing fixture labels and old receipts remain.

## D-184 (2026-10-27): compare resolved JS/TS expectations behind stable names

The JS/TS expected-provenance pass skipped an aligned assertion when its
expected operand spelling stayed the same, even if the local definition
changed. Compare the two resolved bindings under the existing rule's subject,
indirectness and shared-producer conditions. `expected = 1` becoming
`expected = 2` behind the unchanged `toBe(expected)` now produces
EXPECTATION_DEFINITION_CHANGED through its existing identity and severity path.

The existing native tolerance event retains ownership of tolerance changes,
preventing duplicate provenance findings. Unchanged canonical values, unknown
resolution and subject/shared-producer controls remain. No new namespace,
finding field, strength value or exemption migration is introduced. This is
the adjacent detector repair within the authorized 0.10.0 core integration;
D-179 separately governs oracle relocation and compensation.

Six new JS/TS controls and the existing expected-provenance module passed on
recorded development source hashes (71 checks total). Final-source validation
remains separate. Original golden fixture labels and failed receipts remain.
