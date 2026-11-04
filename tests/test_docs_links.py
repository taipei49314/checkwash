"""Every relative link between the project's own documents must resolve.

The roadmap tracker shipped as a public issue pointing at
`docs/ROADMAP-top-tier.md` on main, and that file was not on main — it lived
untracked in a second clone. A reader following the canonical plan got a 404.

That is the same shape as the rest of this project's recurring defect: a
pointer that resolves to nothing reads as coverage. The judge files already
cross-reference each other heavily (SPEC → THREATMODEL → DECISIONS →
benchmarks), and a stale path in that web is a silent lie about where the
evidence is.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Relative markdown links only. Absolute URLs are a different problem (they
# need the network to check, and this project does not make network calls).
_LINK = re.compile(r"\]\((\.{0,2}/?[A-Za-z0-9._/-]+\.md)(?:#[A-Za-z0-9._-]+)?\)")


def _documents() -> list[pathlib.Path]:
    docs = sorted(ROOT.glob("docs/**/*.md"))
    top = [
        ROOT / name
        for name in (
            "README.md",
            "SPEC.md",
            "STATE.md",
            "THREATMODEL.md",
            "DECISIONS.md",
            "CONTRIBUTING.md",
            "AGENTS.md",
            "SECURITY.md",
        )
        if (ROOT / name).exists()
    ]
    extra = sorted(ROOT.glob("action/**/*.md"))
    return docs + top + extra + sorted(ROOT.glob("benchmarks/**/*.md"))


def test_every_relative_markdown_link_resolves():
    documents = _documents()
    assert len(documents) >= 12, f"only found {len(documents)} documents; the glob broke"

    broken = []
    checked = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        for link in _LINK.findall(text):
            checked += 1
            if not (path.parent / link).resolve().exists():
                broken.append(f"{path.relative_to(ROOT)} -> {link}")

    # A gate that matched nothing would pass forever; this project has shipped
    # that failure four times, so the count is asserted too.
    assert checked >= 20, f"only {checked} relative links found; the regex broke"
    assert not broken, "documents link to files that do not exist:\n  " + "\n  ".join(broken)


# `[D-194](../DECISIONS.md)`: a link named after a decision entry, to the log or
# one of its archives, with or without a fragment.
_DECISION_LINK = re.compile(
    r"\[(D-\d+)\]\((\.{0,2}/?(?:[A-Za-z0-9._-]+/)*DECISIONS(?:-archive-\d+)?\.md)(?:#[A-Za-z0-9._-]+)?\)"
)
_DECISION_HEADING = re.compile(r"^## (D-\d+)\b", re.MULTILINE)


def test_decision_links_reach_the_file_that_holds_the_entry():
    # The release-time cut (RELEASING, "After the release") moves entries from
    # DECISIONS.md into the next archive. At the v0.11.0 cut (D-197), 50 links
    # named a moved entry, D-188 to D-196, and still pointed at DECISIONS.md:
    # the file existed, so the test above passed, but the entry had left it.
    headings: dict[pathlib.Path, set[str]] = {}
    stale = []
    checked = 0
    for path in _documents():
        for entry, link in _DECISION_LINK.findall(path.read_text(encoding="utf-8")):
            target = (path.parent / link).resolve()
            if target not in headings:
                text = target.read_text(encoding="utf-8") if target.exists() else ""
                headings[target] = set(_DECISION_HEADING.findall(text))
            checked += 1
            if entry not in headings[target]:
                stale.append(f"{path.relative_to(ROOT)}: [{entry}] -> {link}")

    assert checked >= 20, f"only {checked} decision links found; the regex broke"
    assert not stale, "decision links miss the file that holds the entry:\n  " + "\n  ".join(stale)
