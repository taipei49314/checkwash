---
name: Send us a cheat greenwash missed
about: A test-tampering diff that greenwash let through (a false negative)
title: "[missed cheat] "
labels: cheat-of-the-week, false-negative
---

**What the agent did instead of fixing the bug**
<!-- one line: "widened the tolerance", "deleted the assertion", ... -->

**The test file, before:**
```python

```

**The test file, after:**
```python

```

**The production file, if it matters (before / after):**
```python

```

**What greenwash said**
<!-- paste `greenwash check --format json` output, or just "verdict: pass" -->

**Why this is tampering and not an honest fix**
<!-- the bug is still there because... -->

---
By filing this you agree it can become a regression fixture in the public
corpus. You'll be credited in the fixture header and, once triaged, in
the External credits table of `benchmarks/FAILURES.md`. Incoming reports
are reviewed quarterly — see `docs/cheat-cadence.md`.
