# TASK input and syntax diagnostics

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
Other scalar text remains false under the current parser. Block lists are
supported for `scope.allow`; flow lists and inline mappings are not. Comment
lines are supported; a trailing comment on the boolean is part of its value.
A leading BOM prevents front-matter recognition. A trailing `#` comment on an
unquoted scope list item remains part of its literal glob; a hash inside a
fully quoted glob can intentionally be part of the path. Quoted strings are not
converted into YAML booleans. These statements describe the existing parser,
not an expansion of the accepted language.

The CLI now gives non-blocking stderr notes for several recognizable unsupported
forms, including BOMs, unclosed front matter, commented/indented block headers,
invalid boolean forms, inline scope/list forms and trailing scope comments.
It does not repair the text, enable
ignored scope/freeze settings or act as a complete YAML validator. Review both
the intended policy and the parsed result before editing a task. Syntax notes
do not change findings, fingerprints, the JSON/SARIF envelopes or exit policy.

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
supported input. The supplied task still uses the restricted front-matter subset.

These task settings apply only when the caller actually supplies `--task`.
This diagnostic change does not make every managed hook or Action pass a task
file, change empty-scope semantics, or add a YAML runtime dependency.
