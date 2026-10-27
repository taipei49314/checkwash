"""Owned local-route metadata controls; no product, installer or network execution."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_pju_receipt_bridge as legacy
import test_pju_release_bridge as release_legacy


bridge = legacy.bridge
release = release_legacy.R
routes = bridge._ROUTE
evidence = legacy.evidence
PJU = "LAPTOP-01AGNPJU"
LOCAL = "LAPTOP-16NUA5I8"
ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location("route_test_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_route(evidence, host, *, separate=False):
    route = routes.route_for(host)
    evidence["manifest"].update(host=host, provenance=route["provenance"])
    replay = json.loads((evidence["packet"] / "action/replay.json").read_bytes())
    replay.update(host=host, provenance=route["action_provenance"])
    evidence["put_json"]("action/replay.json", replay)
    if separate:
        for path in (evidence["packet"] / "action").iterdir():
            evidence["put"]("candidate-action/" + path.name, path.read_bytes())
        path = evidence["records"]["candidate_action_coverage"]
        coverage = json.loads((evidence["packet"] / path).read_bytes())
        coverage.update(mode="separate-replay", replay_path="candidate-action/replay.json")
        evidence["put_json"](path, coverage)
    return route


@pytest.mark.parametrize("host", [PJU, LOCAL])
@pytest.mark.parametrize("separate", [False, True])
def test_complete_owned_packet_keeps_actual_host_and_same_route_replays(evidence, host, separate):
    route = select_route(evidence, host, separate=separate)
    report = evidence["validate"]()
    assert report["host"] == host
    assert report["provenance"] == route["provenance"]
    assert report["checks"] == list(bridge.CONTEXTS)
    assert report["other_platforms"] == "NOT_RUN"


@pytest.mark.parametrize("field,value", [
    ("host", "another-host"),
    ("host", "laptop-16nua5i8"),
    ("host", None),
    ("provenance", "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL"),
    ("provenance", "HUMAN_AUTHORIZED_LOCAL_OTHER_NOT_EC_POOL"),
])
def test_manifest_cannot_choose_unknown_host_or_another_routes_label(evidence, field, value):
    select_route(evidence, LOCAL)
    evidence["manifest"][field] = value
    with pytest.raises(ValueError, match="receipt host|host/provenance"):
        evidence["validate"]()


@pytest.mark.parametrize("path", ["action/replay.json", "candidate-action/replay.json"])
@pytest.mark.parametrize("mutation", ["other-host", "other-label", "both-other-route", "unknown-host"])
def test_either_action_replay_must_match_its_parent_manifest(evidence, path, mutation):
    select_route(evidence, LOCAL, separate=True)
    replay = json.loads((evidence["packet"] / path).read_bytes())
    if mutation in ("other-host", "both-other-route"):
        replay["host"] = PJU
    if mutation in ("other-label", "both-other-route"):
        replay["provenance"] = "PJU_LOCAL_COMPOSITE_REPLAY"
    if mutation == "unknown-host":
        replay["host"] = "another-host"
    evidence["put_json"](path, replay)
    with pytest.raises(ValueError, match="Action replay identity"):
        evidence["validate"]()


@pytest.mark.parametrize("field,value", [("os", "Linux"), ("python_version", "3.12.0"), ("other_platforms", "passed")])
def test_local_host_extension_keeps_the_existing_runtime_and_missing_platform_limits(evidence, field, value):
    select_route(evidence, LOCAL)
    evidence["manifest"]["runtime"][field] = value
    with pytest.raises(ValueError, match="runtime platform scope"):
        evidence["validate"]()


@pytest.mark.parametrize("host", [PJU, LOCAL])
def test_current_route_uses_actual_node_and_cannot_be_selected_by_environment(monkeypatch, host):
    monkeypatch.setattr(routes, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(routes, "platform", SimpleNamespace(node=lambda: host))
    for name in ("COMPUTERNAME", "HOSTNAME", "CHECKWASH_HOST"):
        monkeypatch.setenv(name, LOCAL if host == PJU else PJU)
    assert routes.current_route()["host"] == host


@pytest.mark.parametrize("os_name,node", [("nt", "unknown-host"), ("posix", LOCAL)])
def test_environment_cannot_rescue_unknown_or_nonwindows_actual_host(monkeypatch, os_name, node):
    monkeypatch.setattr(routes, "os", SimpleNamespace(name=os_name))
    monkeypatch.setattr(routes, "platform", SimpleNamespace(node=lambda: node))
    monkeypatch.setenv("COMPUTERNAME", LOCAL)
    with pytest.raises(ValueError):
        routes.current_route()


def test_collector_and_internal_helper_refuse_unsupported_host_before_work(monkeypatch):
    collector = load_tool("collect_pju_receipts")
    def refuse():
        raise ValueError("unsupported local receipt host")
    action = SimpleNamespace(require=lambda condition, message: None, execution_route=refuse)
    monkeypatch.setattr(collector, "load_replayer", lambda: action)
    with pytest.raises(ValueError, match="unsupported local receipt host"):
        collector.collect(SimpleNamespace())
    with pytest.raises(ValueError, match="unsupported local receipt host"):
        collector.main(["--internal-helper", "tool", "receipt", "arg"])


def test_replayer_refuses_unknown_actual_host_before_any_path_or_action_work(monkeypatch):
    replay = load_tool("replay_pju_action")
    monkeypatch.setattr(replay._ROUTE, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(replay._ROUTE, "platform", SimpleNamespace(node=lambda: "unknown-host"))
    with pytest.raises(ValueError, match="unsupported local receipt host"):
        replay.replay(**dict.fromkeys(("source", "action", "action_sha", "base", "head", "python", "git", "bash", "output", "scratch")))


def test_local_receipt_check_publication_reports_actual_host_without_relabeling(evidence):
    route = select_route(evidence, LOCAL)
    report = evidence["validate"]()
    api = legacy.FakeGitHub(report)
    bridge.publish(api, report, "d" * 64, "e" * 40, "https://github.com/owned/run")
    posts = [body for method, _, body in api.writes if method == "POST"]
    assert [body["name"] for body in posts] == list(bridge.CONTEXTS)
    assert all(LOCAL in body["output"]["summary"] and route["provenance"] in body["output"]["summary"]
               and PJU not in body["output"]["summary"] for body in posts)


def test_unsupported_report_route_cannot_publish_any_receipt_check(evidence):
    report = evidence["validate"]()
    report["host"] = "another-host"
    api = legacy.FakeGitHub(report)
    with pytest.raises(ValueError, match="unsupported local receipt host"):
        bridge.publish(api, report, "d" * 64, "e" * 40, "https://github.com/owned/run")
    assert api.writes == []


def parent_packet(host):
    packet, api, current = release_legacy.ParentStageTests().parent()
    route = routes.route_for(host)
    packet.manifest.update(host=host, provenance=route["provenance"])
    prior = packet.json("parents/pr.json")
    prior.update(host=host, provenance=route["provenance"])
    packet.put_json("parents/pr.json", prior)
    packet.manifest["parents"]["pr"]["sha256"] = release.digest(packet.raw("parents/pr.json"))
    for row in api.data.values():
        if isinstance(row, dict) and "external_id" in row:
            row["output"] = {"summary": native_summary(route)}
    return packet, api, current


def native_summary(route):
    return (f"{route['provenance']}; actual host {route['host']}; Windows/Python 3.11.9. Other platforms NOT_RUN.\n\n"
            "Owned prior release-stage check.")


@pytest.mark.parametrize("host", [PJU, LOCAL])
def test_previous_native_stage_keeps_its_matching_actual_route(host):
    assert release.validate_parents(*parent_packet(host))["stage"] == "pr"


@pytest.mark.parametrize("mutation", ["other-route", "other-label", "unknown-host", "missing-host"])
def test_previous_native_stage_cannot_be_reused_across_execution_routes(mutation):
    packet, api, current = parent_packet(LOCAL)
    prior = packet.json("parents/pr.json")
    if mutation == "other-route":
        prior.update(host=PJU, provenance=routes.route_for(PJU)["provenance"])
    elif mutation == "other-label":
        prior["provenance"] = routes.route_for(PJU)["provenance"]
    elif mutation == "unknown-host":
        prior["host"] = "another-host"
    else:
        prior.pop("host")
    packet.put_json("parents/pr.json", prior)
    packet.manifest["parents"]["pr"]["sha256"] = release.digest(packet.raw("parents/pr.json"))
    with pytest.raises(ValueError, match="route differs|receipt host|host/provenance"):
        release.validate_parents(packet, api, current)


@pytest.mark.parametrize("stage", ["tag", "release-event", "public-visitor"])
@pytest.mark.parametrize("parent_host", [PJU, LOCAL])
def test_every_later_stage_binds_native_parent_to_the_same_local_route(stage, parent_host):
    packet, api, current = later_parent_packet(stage, parent_host)
    if parent_host == LOCAL:
        assert release.validate_parents(packet, api, current)["stage"] == release.PREVIOUS[stage]
    else:
        with pytest.raises(ValueError, match="previous stage execution route differs"):
            release.validate_parents(packet, api, current)


def later_parent_packet(stage, parent_host):
    current = release_legacy.subject(stage)
    api = release_legacy.NativeAPI(current)
    prior_stage = release.PREVIOUS[stage]
    prior = release_legacy.report(prior_stage)
    route = routes.route_for(LOCAL)
    parent_route = routes.route_for(parent_host)
    prior.update(host=parent_host, provenance=parent_route["provenance"])
    packet = release_legacy.MemoryPacket({"host": LOCAL, "provenance": route["provenance"]})
    path = "parents/" + prior_stage + ".json"
    packet.put_json(path, prior)
    packet.manifest["parents"] = {prior_stage: {"report": path, "sha256": release.digest(packet.raw(path)), "check_run_id": 99}}
    api.data[api.prefix + "/check-runs/99"] = dict(id=99, app={"id": 15368},
        status="completed", conclusion="success", name=release.context(prior_stage),
        output={"summary": native_summary(parent_route)},
        head_sha=current["head_sha"], external_id="pju-release:" + prior["manifest_sha256"] + ":" + prior_stage)
    return packet, api, current


def test_rewriting_old_pju_report_cannot_reuse_its_unchanged_native_pju_checks():
    packet, api, current = release_legacy.ParentStageTests().parent()
    prior = packet.json("parents/pr.json")
    original_manifest_digest = prior["manifest_sha256"]
    route = routes.route_for(LOCAL)
    packet.manifest.update(host=LOCAL, provenance=route["provenance"])
    prior.update(host=LOCAL, provenance=route["provenance"])
    packet.put_json("parents/pr.json", prior)
    packet.manifest["parents"]["pr"]["sha256"] = release.digest(packet.raw("parents/pr.json"))
    assert prior["manifest_sha256"] == original_manifest_digest
    assert all(row["output"]["summary"].startswith(routes.route_for(PJU)["provenance"])
               for row in api.data.values() if isinstance(row, dict) and "external_id" in row)
    with pytest.raises(ValueError, match="native check execution route header differs"):
        release.validate_parents(packet, api, current)


@pytest.mark.parametrize("host,style", [(PJU, "legacy"), (PJU, "local"), (PJU, "release"), (LOCAL, "local"), (LOCAL, "release")])
def test_only_actual_historical_or_current_publisher_headers_are_accepted(host, style):
    packet, api, current = parent_packet(host)
    route = routes.route_for(host)
    if style == "legacy":
        summary = f"Real PJU execution: {host}; {route['provenance']}.\n\nOwned native check."
    elif style == "local":
        summary = f"Real local execution: {host}; {route['provenance']}.\n\nOwned native check."
    else:
        summary = native_summary(route)
    for row in api.data.values():
        if isinstance(row, dict) and "external_id" in row:
            row["output"] = {"summary": summary}
    assert release.validate_parents(packet, api, current)["stage"] == "pr"


@pytest.mark.parametrize("check_id", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("mutation", ["missing", "wrong-route", "late-header"])
def test_every_pr_context_and_stage_check_needs_its_exact_native_route_header(check_id, mutation):
    packet, api, current = parent_packet(LOCAL)
    native = api.data[api.prefix + "/check-runs/" + str(check_id)]
    if mutation == "missing":
        native.pop("output")
    elif mutation == "wrong-route":
        native["output"]["summary"] = native_summary(routes.route_for(PJU))
    else:
        native["output"]["summary"] = "Other text before route\n\n" + native["output"]["summary"]
    with pytest.raises(ValueError, match="native check execution route header"):
        release.validate_parents(packet, api, current)


@pytest.mark.parametrize("malformation", ["nonobject", "nonsummary", "nonstr", "substring", "single-newline", "suffix", "legacy-local", "crlf"])
def test_native_route_header_is_not_a_missing_field_or_arbitrary_substring(malformation):
    packet, api, current = parent_packet(LOCAL)
    route = routes.route_for(LOCAL)
    native = api.data[api.prefix + "/check-runs/1"]
    header = native_summary(route).split("\n\n")[0]
    if malformation == "nonobject":
        native["output"] = []
    elif malformation == "nonsummary":
        native["output"] = {}
    elif malformation == "nonstr":
        native["output"]["summary"] = 1
    elif malformation == "substring":
        native["output"]["summary"] = "Untrusted prefix " + header + "\n\nOwned check."
    elif malformation == "single-newline":
        native["output"]["summary"] = header + "\nOwned check."
    elif malformation == "suffix":
        native["output"]["summary"] = header + " extra\n\nOwned check."
    elif malformation == "legacy-local":
        native["output"]["summary"] = f"Real PJU execution: {LOCAL}; {route['provenance']}.\n\nOwned check."
    else:
        native["output"]["summary"] = header + "\r\n\r\nOwned check."
    with pytest.raises(ValueError, match="native check execution route header"):
        release.validate_parents(packet, api, current)


@pytest.mark.parametrize("stage", ["tag", "release-event", "public-visitor"])
def test_every_later_stage_rejects_matching_report_with_native_other_host_header(stage):
    packet, api, current = later_parent_packet(stage, LOCAL)
    api.data[api.prefix + "/check-runs/99"]["output"]["summary"] = native_summary(routes.route_for(PJU))
    with pytest.raises(ValueError, match="native check execution route header differs"):
        release.validate_parents(packet, api, current)


@pytest.mark.parametrize("stage", release.STAGES)
def test_release_stage_publication_keeps_contexts_and_actual_local_route(stage):
    report = release_legacy.report(stage)
    route = routes.route_for(LOCAL)
    report.update(host=LOCAL, provenance=route["provenance"])
    api = release_legacy.NativeAPI(report["subject"])
    release.publish_check(api, report, "https://github.com/owned/run")
    posts = [body for method, _, body in api.writes if method == "POST"]
    expected = [*bridge.CONTEXTS, release.context("pr")] if stage == "pr" else [release.context(stage)]
    assert [body["name"] for body in posts] == expected
    assert all(LOCAL in body["output"]["summary"] and route["provenance"] in body["output"]["summary"]
               and PJU not in body["output"]["summary"] for body in posts)


def test_release_stage_cannot_publish_cross_labeled_report():
    report = release_legacy.report("main")
    report["host"] = LOCAL
    api = release_legacy.NativeAPI(report["subject"])
    with pytest.raises(ValueError, match="host/provenance"):
        release.publish_check(api, report, "https://github.com/owned/run")
    assert api.writes == []
