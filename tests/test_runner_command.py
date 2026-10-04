"""#196 191.5: does one command invoke a test runner?

A runner site is a workflow step or pre-commit hook whose own command runs a
test runner, and `if: false` on one reads as a disabled suite. Row 69's
substring check made `pip install pytest`, `./deploy-majestic.sh` and an echo
of the word into sites, so switching any of them off blocked with a false
reason. The predicate keeps a runner name unless its context is known not to
run it, and keeps every name in text it cannot follow.
"""

import time

import pytest

from checkwash.roles import _TEST_RUNNER_TOKENS, _runs_tests
from checkwash.runner_command import invokes_test_runner, names_test_runner


@pytest.mark.parametrize("command", [
    # A runner name as a whole word, wherever it stands in a command.
    "pytest",
    "python -m pytest -q",
    "coverage run -m pytest && coverage xml",
    "tox -e docs",
    "nox -s tests",
    "python -m unittest discover",
    "npx jest --ci",
    "npx vitest run",
    "bundle exec rspec",
    "./scripts/run-pytest.sh",
    ".venv/bin/pytest",
    "pytest.exe -q",
    "cat tox.ini",
    "PYTEST_ADDOPTS=-x pytest",
    "pytest # run the suite",
    # A tool and its subcommand; the target may go on, as it could before.
    "npm test",
    "npm  test -- --ci",
    "yarn test:unit",
    "pnpm test",
    "go test ./...",
    "cargo test",
    "make test",
    "make tests",
    "make test_unit",
    "gradle test",
    "mvn test",
    "dotnet test",
    # Every wrapper keeps its runner.
    "bash -c 'pytest -q'",
    "sh -c \"echo start; pytest\"",
    "docker compose run --rm web pytest",
    "nix develop --command pytest",
    "sudo -E pytest",
    "env CI=1 pytest",
    "uv run pytest",
    "poetry run pytest",
    "pipx run tox",
    "hatch run test:pytest",
    "xvfb-run -a npm test",
    "if pytest; then echo ok; fi",
    "{ pytest; }",
    "(cd tests && pytest)",
    # An install beside a runner: the runner runs.
    "pip install pytest && pytest",
    "pip install pytest; python -m pytest",
    "npm ci && npm test",
    "apt-get install -y tox && tox",
    # Output that something else runs.
    "echo pytest | sh",
    "printf 'pytest -q\\n' | bash",
    "echo pytest > >(bash)",
    "cat <<EOF | bash\npytest\nEOF",
    # A command substitution runs wherever it stands.
    'echo "$(pytest --version)"',
    "echo `pytest --version`",
    "x=$(echo pytest); $x",
    "pip install $(pytest --version)",
    'echo "${CMD:-$(pytest)}"',
    # A heredoc whose reader runs it, or whose body expands.
    "bash <<EOF\npytest\nEOF",
    "python - <<'EOF'\nimport pytest\nraise SystemExit(pytest.main())\nEOF",
    "ssh runner <<EOF\ncd app && pytest\nEOF",
    "cat <<EOF\n$(pytest)\nEOF",
    # Installers the ruling does not name keep their names.
    "uv tool install tox",
    "yarn global add jest",
    "gem install rspec",
    # Text the lexer cannot follow keeps every name.
    "echo 'unterminated && pytest",
    'echo "unterminated && pytest',
    "echo $(unbalanced pytest",
    "case $x in a) pytest;; esac",
    "echo $(case $x in a) pytest;; esac)",
    "(echo $(case $x in a) pytest;; esac)",
    "cat <<EOF\npytest\n",
    "echo pytest <<EOF",
    "echo $(cat <<EOF\npytest\nEOF\n)",
    'echo "$(cat <<EOF\nnot run\nEOF\n)" pytest',
    "echo pytest )",
    "echo pytest ) (",
    "echo " + "$(" * 2000 + "pytest" + ")" * 2000,
])
def test_a_command_that_runs_a_runner_is_a_site(command):
    assert invokes_test_runner(command)


@pytest.mark.parametrize("command", [
    # Not a whole word.
    "./deploy-majestic.sh",
    "./check-toxicity.sh",
    "rm -rf .tox .nox",
    "python tools/pytest_summary.py",
    "echo TOX_PYTHON=py312 >>$GITHUB_ENV",
    "python -m django test",
    "gmake test",
    # Echo and printf text.
    "echo pytest",
    'echo "Running pytest"',
    "printf 'pytest\\n'",
    "printf '%s\\n' \"run jest\" > notes.txt",
    "echo '$(pytest)'",
    'echo "pytest_args=-x" >> $GITHUB_OUTPUT',
    "echo \"::group::pytest\"",
    "FOO=1 echo pytest",
    "/bin/echo pytest",
    "if [ -n \"$CI\" ]; then echo pytest; fi",
    "echo \"$(date) pytest done\"",
    # Heredoc text that cat, tee, echo or printf writes out.
    "cat <<EOF >> $GITHUB_STEP_SUMMARY\n## pytest results\nEOF",
    "cat <<'EOF' > run.md\n$(pytest)\nEOF",
    "cat > notes.md <<\"EOF\"\nRun `pytest` locally.\nEOF",
    "tee -a out.txt <<-EOF\n\tpytest\n\tEOF",
    # Install commands.
    "pip install pytest",
    "pip3 install --user tox",
    "pip3.12 install pytest",
    "pip.exe install pytest",
    ".venv/bin/pip install pytest pytest-cov",
    "python -m pip install -U pytest pytest-cov",
    "python -Im pip install --upgrade wheel tox",
    "py -m pip install tox",
    "uv pip install --system tox-uv",
    "pipx install tox",
    "poetry add --group dev pytest",
    "npm i -D jest",
    "npm install --save-dev vitest",
    "npm add vitest",
    "yarn add -D jest",
    "sudo apt-get -y install python3-pytest tox",
    "brew install tox",
    "python -m pip install --upgrade pip setuptools wheel\npython -m pip install --upgrade virtualenv tox",
    # Comments.
    "# pytest runs in the test job\nmake -C docs html",
    "make html  # not pytest",
])
def test_a_command_that_does_not_run_a_runner_is_not_a_site(command):
    assert not invokes_test_runner(command)


def test_every_runner_token_counts_as_a_command():
    for token in _TEST_RUNNER_TOKENS:
        assert invokes_test_runner(token), token
        assert invokes_test_runner(f"cd app && {token} --flag"), token
        assert not invokes_test_runner(f"echo {token}"), token


@pytest.mark.parametrize("text, named", [
    ("pmeier/pytest-results-action@v0", True),
    ("./.github/actions/run-pytest", True),
    ("tox-dev/action-pre-commit-uv@v1", True),
    ("ArtiomTr/jest-coverage-report-action@v2", True),
    ("actions/setup-python@v5", False),
    ("codecov/codecov-action@v4", False),
    ("EnricoMi/publish-unit-test-result-action@v2", False),
    ("tox_env", False),
    ("tox-env", True),
])
def test_a_name_counts_as_a_whole_word(text, named):
    assert names_test_runner(text) is named


def test_row_69_still_reads_the_whole_file():
    """The deletion check and the opaque-exemption denial keep the broad check."""
    assert _runs_tests(b"pip install pytest\n")
    assert _runs_tests(b"echo TOX_PYTHON=py312\n")
    assert not invokes_test_runner("pip install pytest")


def test_a_long_command_is_read_in_linear_time():
    """Twelve thousand simple commands: a quadratic reader would take minutes."""
    command = "\n".join(["echo pytest; pip install tox; pytest -q # tox"] * 4_000)
    start = time.perf_counter()
    assert invokes_test_runner(command)
    assert not invokes_test_runner(command.replace("; pytest -q", ""))
    assert time.perf_counter() - start < 5
