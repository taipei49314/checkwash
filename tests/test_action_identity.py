"""The Action invokes the real checkwash package through its verified interpreter.

The old console-script text count described a shell representation. The Action
now delegates to a stdlib driver, whose process tests exercise actual engine
findings, isolation and exit semantics in test_action_security.py.
"""

import ast
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_action_identity_is_checkwash():
    action = (ROOT / "action" / "action.yml").read_text(encoding="utf-8")
    assert action.startswith("name: checkwash")
    assert "greenwash check" not in action
    assert "GREENWASH_" not in action
    assert '"$CW_ACTION_PATH/secure.py" check' in action
    assert '"$CW_ACTION_PATH/secure.py" comment' in action

    tree = ast.parse((ROOT / "action" / "secure.py").read_text(encoding="utf-8"))
    invocations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess"
                or node.func.attr != "run" or not node.args or not isinstance(node.args[0], ast.List)):
            continue
        arguments = node.args[0].elts
        literal = [argument.value if isinstance(argument, ast.Constant) else None for argument in arguments]
        if literal[1:8] == ["-I", "-B", "-X", "utf8", "-m", "checkwash", "check"]:
            invocations.append(arguments)
    assert len(invocations) == 2, "term and JSON passes must invoke the isolated checkwash module"
    for arguments in invocations:
        interpreter = arguments[0]
        assert isinstance(interpreter, ast.Attribute) and interpreter.attr == "executable"
        assert isinstance(interpreter.value, ast.Name) and interpreter.value.id == "sys"


def test_action_readme_names_the_real_command_and_no_stale_version():
    readme = (ROOT / "action" / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# checkwash GitHub Action")
    assert "greenwash check" not in readme
    assert "v0.1.46" not in readme


def test_console_script_alias_is_kept_and_marked_legacy():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["checkwash"] == "checkwash.cli:main"
    assert scripts["greenwash"] == "checkwash.cli:main"
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "legacy alias" in raw
