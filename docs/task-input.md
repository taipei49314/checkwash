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

The reviewed base copy supplies the contract. At the repository root, a missing
base task can still use a working-tree fallback under the existing alias
restrictions, with a separate warning. That copy is controlled by the change;
commit a reviewed task before relying on base-owned policy. From a repository
subdirectory only the base copy is read. Use an absolute repository-owned path
while the separately documented relative-path contract discrepancy is resolved;
do not change the path spelling to bypass a base-tree alias refusal.

These task settings apply only when the caller actually supplies `--task`.
This diagnostic change does not make every managed hook or Action pass a task
file, change empty-scope semantics, or add a YAML runtime dependency.
