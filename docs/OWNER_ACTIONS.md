# OWNER_ACTIONS — greenwash v0.1.13 release candidate

Branch: `closure/greenwash-20260807`  
Cursor must **not** merge, force-push, delete/rewrite tags, or publish the GitHub Release.

## Decision (evidence-level)

`NEW_RELEASE_CANDIDATE` → proposed tag **`v0.1.13`**

Engine (`src/`) is identical to `v0.1.12`. The candidate exists because main carries
visitor-facing honesty/docs/release-infra that the tagged tree lacks
(`benchmarks/FAILURES.md`, `docs/integrations.md`, `docs/stability.md`,
`.github/workflows/release.yml`, zipapp gate tests, README front-door rewrite).
This repository’s own release workflow text calls out tag-behind-main with
better docs as a failure mode.

## Required owner actions

1. **Review** branch `closure/greenwash-20260807` (opens as PR or fast-forward from main tip).
2. **Do not** change detector code or severity tables for this cut unless a
   reproduced bypass lands separately.
3. On the release commit (may be this tip or a follow-up on main):
   - Bump `pyproject.toml` / package `__version__` to **`0.1.13`**
   - Update `STATE.md` authoritative table `version` row to `v0.1.13`
   - Update README install/action/pre-commit pins from `@v0.1.12` → `@v0.1.13`
   - Confirm `tests/test_state_claims.py` and packaging pins still pass
4. **Merge** only after CI is green (matrix test + dogfood + install-from-tag will
   require the new tag to exist for the install-from-tag job — create the tag on
   the merged SHA **before** or such that that job can resolve `refs/tags/v0.1.13`).
5. **Create annotated tag** `v0.1.13` on the merged default-branch SHA.
6. **Publish GitHub Release** `v0.1.13` (human). Prefer draft notes from
   closure evidence `RELEASE_CANDIDATE.md`, then let `.github/workflows/release.yml`
   attach sdist/wheel/zipapp on `release: published`, or use `workflow_dispatch`
   first to inspect artifacts.
7. Confirm release assets: `greenwash-0.1.13-*.whl`, `.tar.gz`, `greenwash.pyz`,
   and publish checksums beside the release notes.

## Explicit non-actions for Cursor

- No merge of own PR
- No force-push
- No tag delete/rewrite
- No GitHub Release publish from this agent
- No new detector without a reproduced bypass case
