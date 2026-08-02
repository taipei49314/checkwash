# Launch notes (internal)

Not shipped to users. The copy and the answers to the questions that will
come. Every number here must match `benchmarks/RESULTS.md` at launch time —
re-check before posting.

## Show HN title (pick one)

1. `Show HN: Greenwash – catch AI agents that weaken your tests to make CI pass (no LLM)`
2. `Show HN: A deterministic detector for diffs that tamper with your test oracle`
3. `Show HN: Greenwash – 0-LLM tripwire for reward hacking in pull requests`

(1) is the default: names the crime, the `no LLM` reversal is a hook without
being the whole pitch. (2) drops "AI/agent" entirely and filters for the
people who know what a test oracle is — use it if the front page is already
AI-saturated that day.

Not a Show HN title, but the strongest line for X / Reddit:
`My agent made the test pass by changing == to > 0. Here's the 0.3s check that caught it.`

## The one-paragraph pitch

Agents make CI green. Sometimes they do it by fixing the bug, and sometimes
by deleting the failing test, widening a float tolerance, or rewriting the
expected value to whatever the broken code returns. Greenwash is a
deterministic, zero-LLM, local-only checker that reads the diff and blocks the
second kind. It analyses the diff, not the code state: a two-sided AST
comparison against an assertion-strength lattice, so `assert x == 105.3`
becoming `assert x > 0` is a finding and a genuine refactor is not. On 1800
human-reviewed commits from six OSS projects it blocks 2.2%; on twelve real
agent tampering diffs it catches 12/12. Zero runtime dependencies, sub-second,
runs on a pre-commit or a stop-hook.

## The five questions, and the answers

1. **"An agent can just rewrite the prod logic so the bad test passes
   honestly."** True, and it's the first documented limit in THREATMODEL.md.
   Greenwash is a tripwire that raises the cost, not a guarantee. It catches
   the cheap, common cheats — the ones that are cheap *because* touching the
   oracle is easier than fixing the code.
2. **"You could write this with an LLM in five minutes."** You could, and it
   would be non-deterministic, need a key, cost per call, and be promptable by
   the diff it's reading. Greenwash is 0.3s, reproducible, and safe as a
   required check. They compose; this is the deterministic layer under an LLM
   reviewer.
3. **"It'll false-positive on every honest test change."** Measured: 2.2% on
   1800 human commits, every repo under 4%, and the progression from 8.6% down
   is public. A finding only blocks on composite evidence (weakened *and* no
   production change that explains it, at symbol level). When it's wrong,
   `greenwash allow --reason` is ten seconds and leaves a reviewed trail.
4. **"Isn't this just mutation testing?"** Mutation testing measures oracle
   strength by running the whole suite, minutes to hours, over all code.
   Greenwash is diff-scoped, sub-second, runs no code, and knows the task
   context. Complementary.
5. **"How is this different from swarm-orchestrator / CodeRabbit / AgentLint?"**
   AgentLint asks "is this code safe/clean" (state-based) — `assert x > 0` is
   perfectly clean, it can't see it. LLM reviewers are cloud, non-deterministic,
   promptable. swarm-orchestrator is the broad cross-ecosystem auditor with a
   runtime-proof gate; greenwash is the narrow deterministic tripwire. There's
   a measured head-to-head in benchmarks/compare/ — including its caveats.

## Prior art, credited up front

swarm-orchestrator, AgentLint, Danger, betterer, mutation testing, SpecBench,
EvilGenie — all in README "Prior art" and THREATMODEL. Crediting them first is
cheaper than being accused of ignoring them.

## Launch-day discipline

- Re-run `greenwash sweep` on all six repos and confirm RESULTS.md before
  posting. No number goes out that a harness didn't just produce.
- Answer the first two hours of HN yourself; the five answers above are
  pre-written so it's fast, not canned.
- Do NOT claim "first" or "only" — the position isn't empty and the README
  says so.
