"""Narrow graph contracts supplement behavior tests of the real validators."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def job(text, name):
    match = re.search(r"^  " + re.escape(name) + r":\n(.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)", text, re.M | re.S)
    assert match, name
    return match[1]


def test_ordinary_ci_runs_the_full_suite_and_public_visitor():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    candidate = job(ci, "test")
    assert re.search(r"^      - run: pytest\s*$", candidate, re.M)
    assert all(token not in candidate for token in ("--ignore", " -k ", " -m ", "continue-on-error"))
    visitor = job(ci, "install-from-tag")
    assert "PRE_TAG_CANDIDATE" not in visitor and "exit 0" not in visitor
    assert "--manifest release/advertised.toml" in visitor
    assert "git worktree add --detach" in visitor
    assert "direct['vcs_info']['commit_id'] == os.environ['RELEASE_COMMIT']" in visitor
    assert "-m checkwash demo" in visitor and "-m checkwash check HEAD~1..HEAD --repo ." in visitor
    assert "continue-on-error" not in visitor


def test_tag_event_validates_its_own_exact_public_identity():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    public = job(ci, "published-source")
    assert "github.ref_type == 'tag'" in public
    assert "RELEASE_TAG: ${{ github.ref_name }}" in public
    assert "RELEASE_COMMIT: ${{ github.sha }}" in public
    assert '--expected-commit "$RELEASE_COMMIT" --source-sha "$RELEASE_COMMIT"' in public
    assert "--remote https://github.com/taipei49314/checkwash.git" in public
    assert "-m checkwash demo" in public and "-m checkwash check HEAD~1..HEAD --repo ." in public


def test_source_and_all_artifact_inventories_precede_any_distribution_upload():
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    build = job(release, "build")
    assert "needs: published-source" in build
    assert "github.event_name == 'release' && needs['published-source'].result == 'success'" in build
    assert "github.event_name == 'workflow_dispatch' && needs['published-source'].result == 'skipped'" in build
    assert "CANDIDATE_SOURCE: ${{ github.sha }}" in build
    upload = build.index("name: dist\n")
    for distribution in ("source", "wheel", "pyz"):
        inventory = build.index("python tools/release_inventory.py --distribution " + distribution)
        assert inventory < upload
        assert "--qualification assertion-receipts/" + distribution + ".json" in build
    assert "continue-on-error" not in build
    # Diagnostic receipts may upload after a failure; distribution artifacts may not.
    dist_step = build[:upload].rsplit("      - uses:", 1)[1]
    assert "if:" not in dist_step


def test_external_publication_requires_both_successful_dependencies_and_release_event():
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    source = job(release, "published-source")
    assert "if: github.event_name == 'release'" in source
    assert "RELEASE_TAG: ${{ github.event.release.tag_name }}" in source
    assert "--expected-commit" in source and "verify_published_source.py" in source
    build = job(release, "build")
    assert "contents: write" not in build and "gh release upload" not in build
    for name in ("publish-assets", "pypi"):
        publisher = job(release, name)
        assert "needs: [published-source, build]" in publisher
        assert "if: github.event_name == 'release'" in publisher
        assert "always()" not in publisher and "continue-on-error" not in publisher
    assert "vars.PYPI_ENABLED == 'true'" in job(release, "pypi")
