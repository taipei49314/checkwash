# Install CheckWash

Use Python 3.11 or later and Git. The current CLI and GitHub Action are
**0.13.1**.

## Install the CLI

Use a Python virtual environment for the [published package](https://pypi.org/project/checkwash/0.13.1/).
If you need to create one, run `python -m venv .venv`. In the commands below,
use `.\.venv\Scripts\python.exe` on Windows or `./.venv/bin/python` on
macOS/Linux in place of `python`. With the environment active, `python`
already selects that interpreter.

```sh
python -m pip install checkwash==0.13.1
python -m checkwash --version
python -m checkwash demo
```

The version command should print `checkwash 0.13.1`. The demo shows the
findings for eight sample changes. To check your uncommitted edits, run this
from your Git repository:

```sh
python -m checkwash check
```

To check the last commit in a repository with at least two commits, use
`python -m checkwash check HEAD~1..HEAD`. Exit 0 means the change passes the
configured threshold, 1 means it blocks, and 2 indicates an error.

## Run the single-file download

You can also [download checkwash.pyz](https://github.com/taipei49314/checkwash/releases/download/v0.13.1/checkwash.pyz).
From the directory where you saved it, run:

```sh
python checkwash.pyz --version
python checkwash.pyz demo
```

## Add the GitHub Action

Copy the [complete pull request workflow](../README.md#use-it-in-ci) to
`.github/workflows/checkwash.yml` in your repository. Its CheckWash step uses
this release commit:

```yaml
      - uses: taipei49314/checkwash/action@62656df812372c085b4d32c7864fcdfaccd0318a # v0.13.1
```

Once the workflow has run, require the `checkwash` status check in your
branch rules to block merges. When upgrading, update the CLI and any local
hooks before changing the Action pin. The [release history](releases/README.md)
links each version's guide and verification record.
