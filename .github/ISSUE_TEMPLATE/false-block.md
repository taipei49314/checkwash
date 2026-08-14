---
name: greenwash blocked honest work
about: greenwash blocked a commit that did not tamper with anything (a false positive)
title: "[false block] "
labels: false-positive
---

**What the commit actually did**
<!-- the honest change: fixed a bug, refactored a helper, bumped a dep, ... -->

**The diff (or the relevant part)**
```diff

```

**What greenwash blocked it with**
<!-- paste `greenwash check --format json`, esp. the rule and escalators -->

**Why it's a false positive**
<!-- the oracle is not actually weaker because... -->

---
Every false positive we've fixed came from a real diff like this one. It'll
become a negative fixture so it can never regress. Reporter credit lands
in `benchmarks/FAILURES.md` (External credits) after the quarterly review
in `docs/cheat-cadence.md`.
