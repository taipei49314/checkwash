# Releasing

The order matters, and it is the whole answer to a question that has now been
asked twice: *the tag-parity gate fails before I cut the tag — isn't that
circular?*

It is not. It is an ordering constraint, and this is the order.

```bash
# 1. bump, in both places
#    src/greenwash/__init__.py  __version__ = "0.1.14"
#    pyproject.toml             version = "0.1.14"

# 2. update the pins the version owns
#    README.md: every @vX.Y.Z and `rev: vX.Y.Z`
#    STATE.md:  the version row of the authoritative table

# 3. commit
git add -A && git commit

# 4. TAG — before anything verifies, and before anything is pushed
git tag -a v0.1.14 -m "..."

# 5. verify. Everything is green here or the release does not happen.
pytest                                  # tag parity is now checkable, and checked
greenwash check --repo .                # the judge judges itself

# 6. push both, together
git push origin main --follow-tags
```

## Why the gate does not get an escape hatch

`tests/test_packaging.py::test_pinned_tag_ships_the_current_source` fails when
the advertised tag does not exist. That is deliberate, and it is not a
theoretical preference: **v0.1.0 shipped pointing at a commit two fixes behind
main**, so visitors read the fixed documentation and installed the unfixed
engine. The gate exists because that happened.

A pre-tag escape hatch — "if the tag is missing, check something weaker and
pass" — was added on 2026-08-08 and removed the same day. It reproduces the
failure mode the assertion's own message describes: *bumping the version used
to make this gate return early and pass*. A gate that passes when its subject
is absent is the "green because it did not run" pattern that has bitten this
project in three separate places (the dogfood job that never executed, the
determinism check that varied the wrong axis, a perf gate that never touched
git).

If a candidate branch's CI is red between the bump and the tag, that is the
gate working. Cut the tag.

## What ships with a release

The `release` workflow builds these on a published release, and refuses to
build if the version and the tag disagree:

- `greenwash-X.Y.Z-py3-none-any.whl` and the sdist — installed into a fresh
  venv in CI, which asserts `pip freeze` contains greenwash and nothing else
- `greenwash.pyz` — the single-file build, gated by `tests/test_zipapp.py`

## PyPI

Not automated by default, on purpose. The `pypi` job is gated behind a
repository environment named `pypi` that does not exist until a human creates
it, and it publishes through trusted publishing, so no token is stored
anywhere by anyone. Two steps, both the maintainer's:

1. Register greenwash as a trusted publisher on PyPI for this repository and
   the `release` workflow.
2. Create the `pypi` environment on the repository.

Until both exist the job is skipped and releases are GitHub-only, which is
what the README currently promises.

## After the release

- Check CI is green on the tag, not just on main.
- `benchmarks/RESULTS.md` and `benchmarks/FAILURES.md` are generated. If the
  round changed anything they summarise, regenerate and commit them —
  `tests/test_state_claims.py` fails if they drift.
- If the round changed detector behaviour, the corpus sweep is not optional.
  If it changed only I/O or documentation, say which targeted checks stood in
  for it, in `DECISIONS.md`, by name.
