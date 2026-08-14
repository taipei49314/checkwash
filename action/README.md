# greenwash GitHub Action

Composite action that installs this repository and runs `greenwash check`
against the PR (or `HEAD~1` on a push).

## Caller workflow

Copy the hash-pinned snippet in the root [README](../README.md).
A tag pin (`actions/checkout@v4`, `taipei49314/greenwash/action@v0.1.34`)
fails zizmor's default `unpinned-uses` policy.

Required in the *caller* workflow, not in this composite file:

- `permissions: contents: read`
- `persist-credentials: false` on checkout
- 40-character commit SHAs on every `uses:`

`setup-python` is in the snippet because the composite runs
`python -m pip install`. The runner image is not a supported Python.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `fail-on` | `high` | Severity that fails the job |
| `base` | PR base SHA, else `HEAD~1` | Left side of the range |

Inputs are passed into the script through `env:`, not interpolated into
`run:`. zizmor 1.29.0 flags `${{ inputs.* }}` inside a `run` block as
`template-injection`.

## Pin lookup

```bash
git ls-remote https://github.com/actions/checkout.git refs/tags/v4.4.0
git ls-remote https://github.com/actions/setup-python.git refs/tags/v5.6.0
git ls-remote https://github.com/taipei49314/greenwash.git refs/tags/v0.1.34
```
