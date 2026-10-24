"""Offline prototype for matching PJU release-stage identities.

This checks identity and digest linkage only. Inputs are data, not authenticated
authority. A trusted adapter must acquire native GitHub observations, resolve
prior reports, and deeply validate all execution evidence before publication.
This prototype never authorizes publication or creates GitHub checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

REPOSITORY = "taipei49314/checkwash"
PROVENANCE = "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL"
PARENTS = {
    "pr": set(),
    "main": {"pr"},
    "tag": {"main"},
    "release-event": {"tag"},
    "public-visitor": {"release-event"},
}
COMMON = {"stage", "repository", "source_sha", "source_tree",
          "event_name", "run_id", "run_attempt", "workflow_sha"}
TAG = {"tag", "tag_object", "tag_type"}
RELEASE = {"release_id", "release_event_run_id", "release_event_run_attempt",
           "release_event_workflow_sha"}
FIELDS = {
    "pr": COMMON | {"pr_number", "base_sha"},
    "main": COMMON | {"ref", "first_parent_sha"},
    "tag": COMMON | TAG,
    "release-event": COMMON | TAG | RELEASE,
    "public-visitor": COMMON | TAG | RELEASE,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_keys(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), label + " fields differ")


def digest(value, length=64):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % length, value), "invalid digest")


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON number: " + value)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def subject(value):
    require(type(value) is dict and type(value.get("stage")) is str
            and value["stage"] in FIELDS, "unknown stage")
    stage = value["stage"]
    exact_keys(value, FIELDS[stage], "subject")
    require(value["repository"] == REPOSITORY, "foreign repository")
    for key in ("source_sha", "source_tree", "base_sha", "first_parent_sha", "tag_object",
                "release_event_workflow_sha", "workflow_sha"):
        if key in value:
            digest(value[key], 40)
    for key in ("pr_number", "release_id", "release_event_run_id", "release_event_run_attempt",
                "run_id", "run_attempt"):
        if key in value:
            require(type(value[key]) is int and value[key] > 0, "invalid native integer: " + key)
    require(value["event_name"] == {"pr": "pull_request", "main": "push", "tag": "push",
            "release-event": "release", "public-visitor": "workflow_dispatch"}[stage], "native event mismatch")
    if stage == "release-event":
        require(value["release_event_run_id"] == value["run_id"]
                and value["release_event_run_attempt"] == value["run_attempt"]
                and value["release_event_workflow_sha"] == value["workflow_sha"], "release event linkage mismatch")
    if stage == "main":
        require(value["ref"] == "refs/heads/main", "main ref mismatch")
    if TAG <= value.keys():
        require(type(value["tag"]) is str and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", value["tag"])
                and value["tag_type"] == "tag", "stable annotated tag required")
    return stage


def validate(admission, receipt, observation):
    """Match admitted data with a stage receipt and an independently read subject.

    No word such as passed or verified in an input can widen this result into
    execution verification. Parent digests must still be resolved and checked
    by a future adapter; this function checks their exact admitted identities.
    """
    keys = {"schema_version", "kind", "subject", "collector_source_sha", "evidence_commit",
            "manifest_sha256", "artifact_set_sha256", "parents"}
    exact_keys(admission, keys, "admission")
    require(type(admission["schema_version"]) is int and admission["schema_version"] == 1
            and admission["kind"] == "checkwash.pju-release-identity-admission.v1", "admission schema")
    stage = subject(admission["subject"])
    exact_keys(receipt, keys | {"host", "provenance", "status"}, "receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
            and receipt["kind"] == "checkwash.pju-release-stage-identity.v1", "receipt schema")
    subject(receipt["subject"])
    subject(observation)
    require(admission["subject"] == receipt["subject"] == observation,
            "stage/native subject mismatch")
    require(receipt["host"] == "LAPTOP-01AGNPJU" and receipt["provenance"] == PROVENANCE
            and receipt["status"] == "completed", "receipt host/status mismatch")
    for key in ("collector_source_sha", "evidence_commit", "manifest_sha256", "artifact_set_sha256"):
        length = 40 if key.endswith(("_sha", "_commit")) else 64
        digest(admission[key], length)
        digest(receipt[key], length)
        require(admission[key] == receipt[key], key + " mismatch")
    for value in (admission["parents"], receipt["parents"]):
        exact_keys(value, PARENTS[stage], "parent stage links")
        for item in value.values():
            digest(item)
    require(admission["parents"] == receipt["parents"], "parent stage digest mismatch")
    return {
        "schema_version": 1,
        "kind": "checkwash.pju-release-identity-result.v1",
        "status": "identity-matched-only",
        "subject": admission["subject"],
        "manifest_sha256": admission["manifest_sha256"],
        "publication_allowed": False,
        "unverified": ["native-observation-authenticity", "maintainer-authorization",
                       "parent-report-resolution", "execution-evidence", "platform-acceptance",
                       "artifact-bytes", "collection-after-event", "public-installations"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("admission", "receipt", "observation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        values = []
        for path in (args.admission, args.receipt, args.observation):
            with path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, "oversized identity input")
            values.append(strict_json(raw))
        result = validate(*values)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        result = {"status": "rejected", "publication_allowed": False, "error": str(error)}
    # Exclusive creation preserves prior results, including rejections.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return 0 if result["status"] == "identity-matched-only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
