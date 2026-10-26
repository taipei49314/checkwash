# TASK policy input

`checkwash check --task /absolute/repository/path/TASK.md` reads a restricted
front-matter subset. It does not parse general YAML. This example uses the
accepted block forms:

```yaml
---
checkwash:
  oracle_freeze: true
  scope:
    allow:
      - src/**
      - tests/**
  intent: preserve the reviewed oracle
---
Task prose follows here.
```

The first line must be the opening `---` after the parser's existing whitespace
strip, with a closing `---` on its own line. Use spaces for indentation and put
`checkwash:` at column 1 on its own line; leading spaces prevent recognition.
The legacy `greenwash:` block is also accepted.
`oracle_freeze` reads an unquoted, case-insensitive `true` scalar as true.
Use bare `true` or `false`. Block lists are supported for `scope.allow`;
flow lists and inline mappings are not. Standalone comment lines are supported.
A hash inside a fully quoted glob can intentionally be part of the path.
Quoted strings are not converted into YAML booleans. Empty scope retains its
existing meaning and does not impose a scope restriction.

Save the file as UTF-8. BASE input must decode strictly; UTF-16, invalid UTF-8
and NUL text refuse instead of becoming an apparently absent contract.
From 0.10.0, authority loading refuses recognized unsupported forms, including
BOMs, unclosed front matter, commented/indented block headers, invalid boolean
forms, inline scope/list forms and trailing comments on policy values. It also
refuses duplicate blocks/fields, unknown or misplaced policy fields, inconsistent
nesting and malformed glob quoting. It reports an engine error before applying
any TASK policy. Term, JSON and SARIF exit 2; the Stop hook reports that the
change was not analysed under its existing error contract. Rewrite the policy
in the canonical block form after review. No YAML coercion or automatic policy
repair occurs.

Application callers should use `checkwash.contract.load_contract`. The
best-effort `parse_contract` decoder remains for reading historical case records;
it deliberately retains the old interpretation and does not validate authority.
The diagnostic helper remains nonmutating. This minor-version change strengthens
the authority entrypoint without rewriting those historical records.

`--task` paths are relative to the directory originally named by `--repo`,
whose default is the invocation directory. For example,
`--repo pkg --task TASK.md` selects `pkg/TASK.md`, even though CheckWash
reviews the whole Git repository after finding its root. Use
`--repo pkg --task ../TASK.md` to select the root contract deliberately, or
use a fully-qualified repository-owned path. Git's BASE copy supplies policy
even when HEAD changes that task. At the root only, a genuinely absent BASE
task may use the working copy with a warning; case/prefix aliases and
subdirectory BASE misses remain refusals. Do not change spelling or resolve
a HEAD symlink to bypass those checks.

On Windows the native path rules also apply: a root-relative task uses the
repo address's drive/share, while same-drive `C:TASK.md` joins that repo
directory. Use fully-qualified paths when portability is important. These
rules do not create a drive mapping or make every symlink/UNC topology a
supported input. The supplied task is still subject to the restricted syntax
validator; a correct lookup is not proof that malformed policy was applied.

These task settings apply only when the caller actually supplies `--task`.
This change does not make every managed hook or Action pass a task
file, change empty-scope semantics, or add a YAML runtime dependency.
