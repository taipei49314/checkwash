# Show HN draft — checkwash v0.3.0 (internal)

**Not shipped to users.** This is the posting copy and the pre-written
answers for the v0.3.0 launch. Every number here must match `STATE.md`'s
authoritative table, `benchmarks/RESULTS.md` and the open current-state
issues **at posting time**. Re-derive each row of §6 before posting.

- **Drafted:** 2026-09-07, against tag `v0.3.0` (commit `4387097`), PyPI
  0.3.0, Release assets as listed in the
  [v0.3.0 public-launch brief](releases/v0.3.0-public-launch.md).
- **Supersedes** the archived pre-rename draft in [`launch.md`](launch.md)
  for posting copy; that file's numbers are the 35/1800 era and its name and
  install pins predate the rename. Its rules in §7 still apply and are
  repeated below.
- **The one fact that shapes this post:** the headline rates in the README
  were measured on engine 0.1.46. v0.3.0 changed detector logic and no fresh
  sweep record is in the repository. Say so in the post, not in a footnote.

---

## 1. Show HN titles

1. `Show HN: Checkwash – a deterministic tripwire for diffs that weaken your tests (no LLM)`
2. `Show HN: Checkwash – my coding agent made CI green by rewriting == into >=`
3. `Show HN: I gave an agent my test-tamper detector's source. It got past it 3 of 3 times`
4. `Show HN: Checkwash – flags test weakening in a Git diff, offline, stdlib-only Python`

(1) is the default: it names the crime and the mechanism and filters for
people who own a test suite. (2) if the front page is agent-saturated that
day; the diff in the post is elicited and the second paragraph says so. (3)
is the honest-loss framing; use it only if you are ready to answer §5 Q3 in
the first ten minutes. Never "first", "only" or "the best".

## 2. The one-paragraph pitch

Coding agents make CI green two ways: by fixing the bug, or by deleting the
failing test, widening a tolerance, rewriting the expected value to whatever
the broken code returns, or making a CI step stop failing. checkwash reads
the Git diff and flags the second kind: deleted or weakened assertions,
disabled tests, relaxed expectations, patched-out subjects, CI checks that no
longer fail. It runs locally, uses no LLM and no network, never executes the
code under review, and emits byte-identical findings on every OS and Python
version it supports. It is alpha, it is measured on a corpus it was tuned on,
and it publishes its own bypass table with the open rows marked open.

## 3. The post body (paste-ready)

# checkwash: a deterministic tripwire for diffs that weaken your tests

A test can keep passing after it stops checking anything useful:

```diff
- assert total == 105.3
+ assert total > 0
```

The new assertion accepts many incorrect totals. checkwash reads your Git
diff and flags known patterns like that one: deleted assertions, skipped
tests, relaxed expectations, patched-out subjects, CI checks that stop
failing. `checkwash check HEAD~1..HEAD` looks at the change, not the code
state, and exits 1 when a configured blocking finding is present.

**What it is not.** When nothing fires the report says "no known tampering
pattern detected", not "no cheating". That wording is fixed in the source
because the second sentence is one a diff-layer tool cannot support. A pass
does not prove a change is correct or honest.

**Runs locally. No LLM. No network during analysis. Never executes your
code.** Pure-stdlib Python 3.11+, one `.pyz` file or `pipx install
checkwash`. The release CI builds the corpus findings on Linux, macOS and
Windows across Python 3.11–3.13 and fails if the nine outputs are not
byte-identical; that gate caught a Python 3.13 divergence in the
release candidate this week (`ast.dump` changed its default output), which
is now fixed and is the kind of thing "deterministic" has to mean in
practice.

**The numbers, with their provenance.** On six popular pure-Python
repositories, 300 consecutive human commits each: **42/1800 blocked
(2.33%)**, of which **27 (1.50%) were adjudicated false positives** and 15
(0.83%) really do drop oracle coverage with nothing visible replacing it.
Those are in-sample numbers on a corpus the detectors were tuned against,
measured on engine **0.1.46**, adjudicated 2026-08-26, and regenerated from
tracked sweep JSONs by a script rather than typed. The release you can
install today is **0.3.0**, which changed detector logic; a fresh sweep on
it is not checked in yet, so read 2.33% as the older engine's rate. Twelve
constructed agent tasks with must-fail tests: **12/12 blocked**. The diff at
the top of this post is elicited — the agent was told to reach green without
fixing the bug — and the repo says so wherever it shows one.

**Where it fails (read this before the numbers above).** The bypass table
is public and not all of it says Closed: 118 rows, 19 marked Open and 9 in
other non-Closed states. On a dedicated refactor corpus, 24 of 60 honest
refactors were blocked; the general-commit rate does not predict that
population. An informed agent given the full source got past the
then-shipped engine three times out of three; the writeup is in the repo. The recorded LLM
stress arm is worse than the human corpus: on v0.2.13, **85 of 88 recorded
escape families still passed** and **90 of 90 recorded honest refactors
still blocked** — 60 of those 90 are a single family, consolidating N named
tests into one parametrize, fixture or loop, which the engine read as
disabling tests. v0.3.0's parametrize-row and table-oracle changes are the
first cut at exactly that family; the re-judge on 0.3.0 is not in the repo
yet, so the numbers above stay as the honest current record.

**Day one, three commands, all offline:**

```bash
pipx install checkwash==0.3.0
checkwash check HEAD~1..HEAD
checkwash check HEAD~1..HEAD --format sarif
```

Or download the single file and check its hash first:

```bash
curl -LO https://github.com/taipei49314/checkwash/releases/download/v0.3.0/checkwash.pyz
sha256sum checkwash.pyz   # 51b4cc86cef3b50b3ebf47fbf2fa4006b9861ef46639b84755eea27b86354af5
python checkwash.pyz demo
```

`demo` replays eight recorded tampering cases and one honest fix from the
repo's own fixtures. It illustrates known patterns; it is not a coverage
guarantee.

**Prior art:** grep, the linters you already run, mutation testing and
coverage ratchets each cover part of this. Grep for `|| true` and
`pytest.mark.skip` today; checkwash exists for the part grep cannot see —
two-sided comparison of what the assertion could distinguish before and
after.

**What I want from you:** the diff it did not catch, the honest refactor it
blocked, and the platform it broke on. Every escape gets a row in the
bypass table with its status, and the suite fails if a Closed row has no
fixture behind it.

Repo: https://github.com/taipei49314/checkwash — PyPI:
https://pypi.org/project/checkwash/0.3.0/ — Apache-2.0.

## 4. Short versions

**X (single post):** checkwash 0.3.0 — flags diffs that weaken your tests
(deleted asserts, skipped tests, `==` → `>=`, CI steps that stop failing).
Local, no LLM, no network, byte-identical on every OS/Python. Alpha; bypass
table public, ~20 rows open. `pipx install checkwash`.

**r/Python:** same as the post body §3 minus the informed-adversary
paragraph; lead with the diff and the three commands.

## 5. Hostile questions, in the order they will arrive

**1. "2.33% means one commit in forty-three fails CI. Nobody keeps that on."**
2.33% is the block rate on a tuning corpus at engine 0.1.46; 1.50% is the
adjudicated false-positive rate and 0.83% are commits that really drop
oracle coverage. The default only blocks `high`; everything else warns.
The current engine's rate on that corpus is not published yet — see Q15.

**2. "An agent will just rewrite the production code so the weak test passes honestly."**
Bounded, not pointless: that is threat model item #1 and the route the
informed agent took on the `rounding` task. checkwash's own message for
that case is "no known tampering pattern detected", and that is correct.

**3. "Your informed arm got past you three times out of three."**
Yes, under the strongest condition — full source, full threat model,
unlimited retries against the real CLI — and it is published rather than
found by you. Three of six tasks were refused by the provider's safety
filter, so the sample is three, not six. Say all of that before the score.

**4. "You adjudicated your own false positives."**
Kappa 0.844 measures agreement among three raters on the 35-diff cohort,
not correctness; the other cohorts had one reviewer and the README says so.
The adjudication JSON and the sweep JSONs are tracked; re-run
`benchmarks/make_results.py` and you get the same table.

**5. "The diff at the top is elicited. Does this happen unprompted?"**
The post says it is elicited, and the natural-condition probe arms in the
repo are small and mostly quiet. The recorded LLM stress arm (Q7) is where
it does happen, and that record is worse for the tool than the human corpus.

**6. "Six mature pure-Python repos is the friendliest corpus."**
Yes, and the repo says so next to the number. 24/1800 commits carry an
opaque-production-change flag; JS/TS support covers a limited set of test
patterns; anything non-Python is out of scope.

**7. "Your own issue says 85 of 88 escapes still pass. Why would I install this?"**
Because the issue exists and is open. Those 88 families were written by a
model told to reach green without fixing the bug, against v0.2.8, and
re-judged on v0.2.13; the 90 false blocks in the same record are mostly one
consolidation family that 0.3.0 targets first. Install it for the part
that works — the human-corpus rate and the twelve decoys — and send the
escapes; each becomes a row.

**8. "Regex-and-AST rules against an adversary is a losing game."**
That is the audit's finding quoted in the threat model: a list that knew
one spelling knew none. It is why exemptions are now bound to content, why
parametrize rows have identities, and why the open rows stay marked open.

**9. "This is a linter with extra steps. I'll grep."**
Do. What grep cannot do is two-sided comparison: `assert x > 0` is clean
code; it is a finding only because the line it replaced was `assert x ==
105.3` and the production diff did not justify the change.

**10. "Why not have an LLM review the diff?"**
For the semantic layer it would catch more. It is also non-deterministic,
costs per call, needs a key, and sees your code. checkwash is the cheap,
deterministic, offline layer under that, and it says which layer it is.

**11. "Isn't this mutation testing or a coverage ratchet?"**
Different axis. Mutation testing runs the suite for minutes to hours over
all code; a ratchet notices a line stopped executing. Neither sees an
expected value rewritten to the buggy result in the same diff.

**12. "How is 'Closed' more than your word?"**
Each Closed row names the fixture pinning it and the test suite fails if a
Closed row has nothing behind it. Open rows are listed as Open.

**13. "You publish your own bypasses. That's a manual for attackers."**
It is, and the informed arm proves it read it. A private list would just be
a list the author knows; a public one is a list that gets shorter.

**14. "Seventeen tags in seven days. That reads like churn."**
It was: v0.1.48 through v0.3.0 between 2026-09-01 and 2026-09-07. The
release cadence is frozen after 0.3.0 while the current records get
re-judged; each release has a dated `STATE.md` section saying what moved
and what it cost.

**15. "Your headline rate was swept at 0.1.46 but you ship 0.3.0."**
Correct, and both the README and `RESULTS.md` stamp it. 0.3.0 changed
detector logic; the repository's own release process says the six-repo
sweep is not optional in that case, and it is not checked in yet. Until it
is, the honest reading is: the 0.1.46 engine measured 2.33% on that corpus;
0.3.0's number is pending.

**16. "PyPI since when? Is this shippable?"**
On PyPI since 0.2.1 through the release workflow's trusted publishing; the
wheel and sdist digests match the GitHub Release assets, and the single
file's SHA-256 is in the post.

**17. "What stops the agent from deleting the hook or editing your config?"**
Deleting the hook: nothing, and it is documented as out of scope — pair it
with the CI required check, which is why the Action ships. Editing the
config or the exemption ledger in the same diff is itself a finding.

**18. "You broke determinism on Python 3.13 and only noticed at release."**
Yes: the byte-compare gate had been skipped while an unrelated tag-parity
check was red, and it fired the first time it ran on the release candidate.
The fix pins the pre-3.13 `ast.dump` format, keys computed on 3.11/3.12 did
not change, and the released commit is green on all nine OS/Python legs. The
lesson is in the release notes, not hidden.

## 6. Numbers in this file — re-verify in one pass

| number | value | source of truth |
|---|---|---|
| version | 0.3.0 | `pyproject.toml`; `STATE.md` authoritative table |
| detectors | 21 | `STATE.md` authoritative table |
| human-commit block rate | 42/1800 = 2.33% | `STATE.md`; `benchmarks/RESULTS.md` (engine 0.1.46, adjudication 2026-08-26) |
| adjudicated false positive | 27/1800 = 1.50% | same |
| legitimate policy block | 15/1800 = 0.83% | same |
| opaque production changes | 24/1800 = 1.33% | same |
| classic decoys blocked | 12/12 | `STATE.md`; `benchmarks/decoy/` |
| honest refactors blocked, dedicated refactor corpus | 24/60 | `README.md` measurements section |
| three-rater cohort kappa | 0.844 (35 diffs) | `STATE.md` |
| bypass table rows / Open / other non-Closed | 118 / 19 / 9 | `THREATMODEL.md` (count the status column at posting time) |
| informed-adversary arm | 3 of 3 passed, 3 of 6 tasks refused by the provider | `THREATMODEL.md` rows 70–73; `launch.md` §"where it fails" (historical, 2026-08-07) |
| tags 2026-09-01 → 2026-09-07 | 17 (v0.1.48 … v0.3.0) | `git tag --sort=creatordate` |
| LLM stress arm on v0.2.13 | 85/88 escapes pass; 90/90 honest blocked; 60/90 one family | issues #132, #130 |
| release asset SHA-256 (pyz) | `51b4cc86cef3…54af5` | Release v0.3.0; `docs/releases/v0.3.0-public-launch.md` |
| CI legs byte-identical | 9/9 | `ci.yml` byte-compare job on commit 4387097 |

Anything not in this table does not go in the post.

## 7. Launch-day discipline

**Blockers — do not post until these are decided.**

1. **The 0.3.0 sweep.** `RELEASING.md` says a round that changes detector
   behaviour must re-sweep the corpus. Either land the sweep record and its
   adjudication for 0.3.0 before posting, or keep the post's wording that
   the published rate is the 0.1.46 engine's. Do not blend the two.
2. **The re-judge of the LLM arm on 0.3.0.** Issues #130/#132 describe
   v0.2.13. If a 0.3.0 re-judge exists by posting day, put its numbers in
   the issues first, then in §6; otherwise the post keeps the v0.2.13 record.
3. **Maintainer pass.** `THREATMODEL.md` and `SPEC.md` rows for the
   parametrize-identity and table-delegation changes, and the `STATE.md`
   narrative for the 0.3.0 section, are human-only edits and are still
   pending. The post must not claim a row is Closed that the file does not.
4. **README links.** The README's usage-guide link points at the v0.2.13
   guide; decide whether to point it at the v0.3.0 brief (this changes the
   GitHub README only; the PyPI description stays as published).

**Standing rules** (unchanged from the archived draft).

- No number goes into the post until a harness produced it on a clean
  checkout; numbers that exist only in a design document are not results.
- Never claim "first", "only" or "the best"; credit prior art up front.
- Never write "no cheating". The report wording is "no known tampering
  pattern detected" and the framing is a tripwire that raises the cost of
  cheating.
- Publish the conditions before the score, every time.
- Do not quote the friendlier count; say how many rows are Open.
- Answer the first two hours yourself; edit the §5 answers to the comment
  actually made. When someone finds a real defect, say so, open the row,
  thank them.
