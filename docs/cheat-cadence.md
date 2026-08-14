# External cheat cadence

The issue templates already exist:

- `.github/ISSUE_TEMPLATE/send-us-a-cheat.md` — a tampering diff
  greenwash let through
- `.github/ISSUE_TEMPLATE/false-block.md` — an honest commit it
  blocked

This page is the review rhythm so those templates are not a dead
letterbox. Roadmap T3.4.

## Cadence

Once a quarter, the maintainer (or whoever is on triage) opens:

```bash
gh issue list --repo taipei49314/greenwash --label cheat-of-the-week,false-positive --state all --limit 50
```

For each new report since the last review:

1. Reproduce with `greenwash check --format json` on the before/after.
2. If it is a real miss or a real false block: add a `.gwcase` fixture,
   credit the reporter in the fixture header, and — if it is a new
   shape — a THREATMODEL row (maintainer-only).
3. Add a row to `benchmarks/external-credits.json`.
4. Regenerate `benchmarks/FAILURES.md` (`python benchmarks/make_failures.py`).

The FAILURES page then carries an **External credits** section. That
section is generated; an empty table means no external report has been
credited yet, not that the column was forgotten.

## What counts as external

A report from someone who is not the author of this repository, filed
through the templates or an equivalent public issue. Internal red-team
findings and the decoy harvest stay in the other FAILURES tables.

Do not invent a credit to fill the table. An empty generated section
is the honest state.

## Why a quarter, not a week

The label on the cheat template is historical (`cheat-of-the-week`).
The review is quarterly because a weekly ritual with no incoming
issues becomes a green checkbox. The templates stay open all the time;
the cadence is the *sweep*, not the inbox.
