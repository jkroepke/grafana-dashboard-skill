#!/usr/bin/env python3
"""Verify the complete dashboard artifact DAG and optionally promote its candidate."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any

import validate_workflow_artifact as artifact
import verify_candidate_render as candidate_render
import verify_dashboard_contract as dashboard_contract
import verify_non_prometheus_preservation as non_prometheus
import verify_query_parity as query_parity


class ChainError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ChainError(message)


def checked(
    path: Path, bindings: dict[str, Path], supports: dict[str, Path] | None = None
) -> tuple[bytes, dict]:
    raw, data = artifact.read_artifact(path)
    arguments = [f"{name}={input_path}" for name, input_path in bindings.items()]
    support_arguments = [f"{name}={input_path}" for name, input_path in (supports or {}).items()]
    inputs, _ = artifact.load_and_bind_inputs(data, arguments, support_arguments)
    artifact.validate_artifact(data, len(raw), inputs, path)
    return raw, data


def regular_digest(path: Path, label: str) -> str:
    require(not path.is_symlink(), f"{label} must not be a symlink")
    require(path.is_file(), f"{label} must be a regular file")
    try:
        return artifact.sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ChainError(f"cannot read {label}: {error}") from error


def rendered_consumers(root: dict[str, Any]) -> dict[query_parity.Locator, query_parity.Consumer]:
    if isinstance(root.get("spec"), dict) and isinstance(root["spec"].get("elements"), dict):
        return query_parity.v2_consumers(root)
    return query_parity.classic_consumers(root)


def rendered_panels(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if isinstance(root.get("spec"), dict) and isinstance(root["spec"].get("elements"), dict):
        return {
            str(name): panel
            for name, panel in root["spec"]["elements"].items()
            if isinstance(panel, dict) and panel.get("kind") == "Panel"
        }
    if isinstance(root.get("dashboard"), dict):
        root = root["dashboard"]
    result: dict[str, dict[str, Any]] = {}
    for panel in query_parity.walk_classic_panels(root.get("panels")):
        panel_id = panel.get("id")
        require(isinstance(panel_id, int) and not isinstance(panel_id, bool),
                "every classic panel must have a numeric id")
        key = f"panel-{panel_id}"
        require(key not in result, f"duplicate classic panel id {panel_id}")
        result[key] = panel
    return result


def verify_change_classification(
    run: dict[str, Any],
    plan: dict[str, Any],
    pack: dict[str, Any],
    candidate_root: dict[str, Any],
    baseline_root: dict[str, Any] | None,
) -> None:
    after_panels = rendered_panels(candidate_root)
    planned_panels = {item["id"]: item for item in plan["panels"]}
    require(set(after_panels) == set(planned_panels),
            "rendered panel IDs must exactly match the dashboard plan")
    if baseline_root is None:
        require(all(item["change"] == "NEW" for item in plan["questions"]),
                "new dashboard contains a non-NEW question")
        require(all(item["change"] == "NEW" for item in plan["panels"]),
                "new dashboard contains a non-NEW panel")
        require(all(item["change"] == "NEW" for item in pack["queries"]),
                "new dashboard contains a non-NEW query")
        return

    before_queries = rendered_consumers(baseline_root)
    after_queries = rendered_consumers(candidate_root)
    require(set(before_queries) <= set(after_queries),
            "candidate removes an existing Prometheus consumer")
    for record in pack["queries"]:
        locator_data = record["consumer_locator"]
        locator = (locator_data["kind"], locator_data["name"], locator_data["ref_id"])
        before = before_queries.get(locator)
        after = after_queries[locator]
        actual = "NEW" if before is None else ("PRESERVED" if before == after else "MODIFIED")
        require(record["change"] == actual,
                f"query {record['id']} change classification must be {actual}")

    before_panels = rendered_panels(baseline_root)
    require(set(before_panels) <= set(after_panels), "candidate removes an existing panel")
    panel_changes: dict[str, str] = {}
    for panel_id, record in planned_panels.items():
        require(panel_id in after_panels, f"planned panel {panel_id} is absent from candidate")
        before = before_panels.get(panel_id)
        actual = "NEW" if before is None else (
            "PRESERVED" if before == after_panels[panel_id] else "MODIFIED"
        )
        require(record["change"] == actual,
                f"panel {panel_id} change classification must be {actual}")
        panel_changes[panel_id] = actual
    for panel_id, before in before_panels.items():
        if panel_id not in planned_panels:
            require(after_panels[panel_id] == before,
                    f"unplanned existing panel {panel_id} changed")

    for question in plan["questions"]:
        changes = [
            panel_changes[panel["id"]]
            for panel in plan["panels"]
            if question["id"] in panel["question_ids"]
        ]
        require(bool(changes), f"question {question['id']} has no panel")
        if all(change == "PRESERVED" for change in changes):
            actual = "PRESERVED"
        elif all(change == "NEW" for change in changes):
            actual = "NEW"
        else:
            actual = "MODIFIED"
        require(question["change"] == actual,
                f"question {question['id']} change classification must be {actual}")


def atomic_exchange(first: Path, second: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    first_raw = os.fsencode(first)
    second_raw = os.fsencode(second)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        operation = libc.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(first_raw, second_raw, 0x00000002)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        operation = libc.renameat2
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        result = operation(-100, first_raw, -100, second_raw, 0x00000002)
    else:
        raise ChainError("atomic exchange is unavailable on this platform")
    if result != 0:
        error_number = ctypes.get_errno()
        raise ChainError(f"atomic exchange failed with errno {error_number}")


def promote(
    run: dict[str, Any],
    build: dict[str, Any],
    candidate_path: Path,
    final_path: Path,
    baseline_digest: str | None,
) -> None:
    if baseline_digest is None:
        try:
            os.link(candidate_path, final_path, follow_symlinks=False)
        except OSError as error:
            raise ChainError(f"atomic no-clobber promotion failed with errno {error.errno}") from error
        try:
            candidate_render.verify(run, build, final_path)
        except (candidate_render.RenderError, OSError) as error:
            final_path.unlink(missing_ok=True)
            raise ChainError(f"promoted source verification failed: {error}") from error
        candidate_path.unlink()
        return

    atomic_exchange(candidate_path, final_path)
    try:
        require(regular_digest(candidate_path, "exchanged baseline source") == baseline_digest,
                "destination changed during atomic promotion")
        candidate_render.verify(run, build, final_path)
    except (ChainError, candidate_render.RenderError, OSError) as error:
        atomic_exchange(candidate_path, final_path)
        raise ChainError(f"promotion rolled back: {error}") from error
    candidate_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_contract", type=Path)
    parser.add_argument("metrics_contract", type=Path)
    parser.add_argument("dashboard_plan", type=Path)
    parser.add_argument("query_pack", type=Path)
    parser.add_argument("query_review", type=Path)
    parser.add_argument("dashboard_build", type=Path)
    parser.add_argument("dashboard_review", type=Path)
    parser.add_argument("--application-metrics", type=Path)
    parser.add_argument("--kubernetes-metrics", type=Path)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    try:
        run_raw, run = checked(args.run_contract, {})
        require(run["status"] == "PASS", "run contract is not PASS")
        run_binding = {"run-contract": args.run_contract}

        shortlist_bindings: dict[str, Path] = {}
        if args.application_metrics is not None:
            _, app = checked(args.application_metrics, run_binding)
            require(app["status"] == "DONE", "application metrics is not DONE")
            shortlist_bindings["application-metrics"] = args.application_metrics
        if args.kubernetes_metrics is not None:
            _, kube = checked(args.kubernetes_metrics, run_binding)
            require(kube["status"] == "DONE", "Kubernetes metrics is not DONE")
            shortlist_bindings["kubernetes-metrics"] = args.kubernetes_metrics
        require(bool(shortlist_bindings), "at least one metric shortlist is required")

        metrics_inputs = run_binding | shortlist_bindings
        _, metrics = checked(args.metrics_contract, metrics_inputs)
        require(metrics["status"] == "PASS", "metrics contract is not PASS")

        plan_inputs = run_binding | {"metrics-contract": args.metrics_contract}
        _, plan = checked(args.dashboard_plan, plan_inputs, shortlist_bindings)
        require(plan["status"] == "PASS", "dashboard plan is not PASS")

        pack_inputs = plan_inputs | {"dashboard-plan": args.dashboard_plan}
        pack_raw, pack = checked(args.query_pack, pack_inputs, shortlist_bindings)
        require(pack["status"] == "PASS", "query pack is not PASS")

        query_review_inputs = pack_inputs | {"query-pack": args.query_pack}
        review_raw, query_review = checked(args.query_review, query_review_inputs, shortlist_bindings)
        require(query_review["status"] == "PASS", "query review is not PASS")

        build_inputs = run_binding | {
            "metrics-contract": args.metrics_contract,
            "dashboard-plan": args.dashboard_plan,
            "query-pack": args.query_pack,
            "query-review": args.query_review,
        }
        build_raw, build = checked(args.dashboard_build, build_inputs, shortlist_bindings)
        require(build["status"] == "PASS", "dashboard build is not PASS")

        dashboard_review_inputs = run_binding | {
            "dashboard-plan": args.dashboard_plan,
            "query-pack": args.query_pack,
            "query-review": args.query_review,
            "dashboard-build": args.dashboard_build,
        }
        review_supports = {"metrics-contract": args.metrics_contract} | shortlist_bindings
        _, dashboard_review = checked(args.dashboard_review, dashboard_review_inputs, review_supports)
        require(dashboard_review["status"] == "PASS", "dashboard review is not PASS")

        candidate_render_raw = candidate_render.verify(run, build)
        candidate_root = json.loads(candidate_render_raw)
        dashboard_contract.verify(candidate_root)
        expected_consumers, _ = query_parity.approved_consumers(pack)
        actual_consumers = rendered_consumers(candidate_root)
        require(expected_consumers == actual_consumers, "approved/rendered query parity failed")

        source = run["source"]
        final_path = Path(source["final_path"])
        candidate_path = Path(source["candidate_path"])
        candidate_digest = regular_digest(candidate_path, "candidate source")
        require(candidate_digest == build["candidate_sha256"] == dashboard_review["candidate_sha256"],
                "candidate digest is not the reviewed digest")

        require(not final_path.is_symlink(), "final source must not be a symlink")
        if source["baseline_state"] == "PRESENT":
            require(regular_digest(final_path, "final source") == source["baseline_sha256"],
                    "final source changed after baseline capture")
            baseline_raw = candidate_render.render_source(run, final_path)
            baseline_root = json.loads(baseline_raw)
        else:
            require(not final_path.exists(), "final source appeared after absent baseline capture")
            baseline_root = None

        non_prometheus.verify(candidate_root, baseline_root)
        verify_change_classification(run, plan, pack, candidate_root, baseline_root)

        require(final_path.parent == candidate_path.parent, "candidate and final source are not adjacent")
        if args.promote:
            promote(run, build, candidate_path, final_path, source["baseline_sha256"])
            require(regular_digest(final_path, "promoted source") == candidate_digest,
                    "promoted source digest mismatch")
            print(f"PASS workflow promoted {candidate_digest}")
        else:
            print(
                "PASS workflow chain "
                f"run={artifact.sha256_bytes(run_raw)} pack={artifact.sha256_bytes(pack_raw)} "
                f"query_review={artifact.sha256_bytes(review_raw)} build={artifact.sha256_bytes(build_raw)}"
            )
    except (
        artifact.ArtifactError,
        candidate_render.RenderError,
        dashboard_contract.ContractError,
        non_prometheus.PreservationError,
        query_parity.ParityError,
        ChainError,
        KeyError,
        OSError,
        TypeError,
    ) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
