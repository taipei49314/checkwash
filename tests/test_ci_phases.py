"""Narrow graph contracts supplement behavior tests of the real validators."""
import ast
from pathlib import Path
import re
import shlex

import yaml

ROOT = Path(__file__).resolve().parents[1]


def job(text, name):
    match = re.search(r"^  " + re.escape(name) + r":\n(.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)", text, re.M | re.S)
    assert match, name
    return match[1]


def release_workflow():
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def runs_tool(value, mode):
    commands = [shlex.split(step["run"]) for step in value["steps"] if "run" in step]
    return any(command[:5] == ["python", "-I", "-B", "trusted/tools/pju_release_bridge.py", mode]
               for command in commands)


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def calls(node, name):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)
            and ast.unparse(item.func) == name]


def test_ordinary_ci_runs_the_full_suite_and_public_visitor():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    candidate = job(ci, "test")
    assert re.search(r"^      - run: pytest -n 2 --dist worksteal\s*$", candidate, re.M)
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
    jobs = release_workflow()["jobs"]
    assert runs_tool(jobs["verify-pju-release"], "verify")
    assert jobs["verify-pju-release"]["permissions"]["contents"] == "read"
    assert jobs["verify-pju-release"]["permissions"]["checks"] == "read"
    assert jobs["publish-pju-stage-check"]["needs"] == "verify-pju-release"
    assert runs_tool(jobs["publish-pju-stage-check"], "publish-check")
    assert set(jobs["publish-assets"]["needs"]) == {"verify-pju-release", "publish-pju-stage-check"}
    assert runs_tool(jobs["publish-assets"], "publish-assets")

    # Inspect executable validator calls, so a comment or a placeholder job
    # cannot stand in for the source/qualification/member-byte checks.
    bridge = ast.parse((ROOT / "tools/pju_release_bridge.py").read_text(encoding="utf-8"))
    product = function(bridge, "validate_product")
    distributions = next(node for node in ast.walk(product) if isinstance(node, ast.For)
                         and isinstance(node.iter, ast.Tuple)
                         and [ast.literal_eval(value) for value in node.iter.elts] == ["source", "wheel", "pyz"])
    assert calls(product, "B.validate_contract")[0].lineno < distributions.lineno
    for validator in ("B.validate_qualification", "validate_qualification_raw", "B.validate_inventory"):
        assert calls(distributions, validator)
    packet = function(bridge, "validate_packet")
    assert calls(packet, "validate_product")[0].lineno < calls(packet, "validate_verdict")[0].lineno
    assert calls(packet, "validate_verdict")[0].lineno < calls(packet, "validate_visitors")[0].lineno
    admitted = function(bridge, "verify_admitted")
    assert calls(admitted, "validate_packet")
    entry = function(bridge, "main")
    assert calls(entry, "verify_admitted")[0].lineno < calls(entry, "publish_assets")[0].lineno

    # Hosted artifact uploads here are diagnostic JSON only. PyPI's dist is
    # exported by the verifier after successful actual GitHub asset readback.
    for value in jobs.values():
        for step in value["steps"]:
            if step.get("uses", "").startswith("actions/upload-artifact@") and "path" in step["with"]:
                assert step["with"]["path"].endswith(".json") or step["with"]["path"] == "native-capture/"
            assert "continue-on-error" not in step


def test_external_publication_requires_both_successful_dependencies_and_release_event():
    release = release_workflow()
    trigger = release.get("on", release.get(True))
    assert trigger["release"]["types"] == ["published"]
    jobs = release["jobs"]
    capture = jobs["capture-native-subject"]
    assert capture["if"] == "github.event_name == 'release' || inputs.mode == 'capture'"
    assert runs_tool(capture, "capture")
    assert capture["permissions"]["contents"] == "read"
    assert "id-token" not in capture["permissions"] and "checks" not in capture["permissions"]
    publish_condition = "github.event_name == 'workflow_dispatch' && inputs.mode == 'publish' && fromJSON(inputs.admission).stage == 'release-event'"
    assets, pypi = jobs["publish-assets"], jobs["pypi"]
    assert assets["if"] == publish_condition
    assert set(assets["needs"]) == {"verify-pju-release", "publish-pju-stage-check"}
    assert pypi["needs"] == "publish-assets"
    assert pypi["if"] == publish_condition + " && vars.PYPI_ENABLED == 'true'"
    assert pypi["environment"] == "pypi" and pypi["permissions"]["id-token"] == "write"
    assert runs_tool(pypi, "verify-assets")
    publisher = next(step for step in pypi["steps"] if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert "if" not in publisher and "continue-on-error" not in publisher
    assert publisher["with"]["packages-dir"] == "dist/"
    for name in ("verify-pju-release", "publish-pju-stage-check", "publish-assets", "pypi"):
        assert "always()" not in jobs[name]["if"] and "continue-on-error" not in jobs[name]

    # The native Release event is observed first; source-bound PJU evidence is
    # admitted later. The validators' owned negative tests cover stale identity,
    # pre-event raw, incomplete qualification and missing publication authority.
    bridge = ast.parse((ROOT / "tools/pju_release_bridge.py").read_text(encoding="utf-8"))
    packet = function(bridge, "validate_packet")
    assert calls(packet, "live_subject") and calls(packet, "validate_parents")
    assert calls(packet, "validate_product") and calls(packet, "validate_visitors")
    upload = function(bridge, "publish_assets")
    assert calls(upload, "publication_authority")[0].lineno < calls(upload, "api.binary")[0].lineno
    assert calls(upload, "live_subject")[0].lineno < calls(upload, "api.binary")[0].lineno
