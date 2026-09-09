#!/usr/bin/env python3
"""Create validated metrics-reviewer rejection or not-considered checkpoints."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import coordinator_stage as stage


class DispositionError(ValueError):
    pass


IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DispositionError(message)


def source_ids(inputs: dict[str, Path]) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for source in {"application-metrics", "kubernetes-metrics"}:
        artifact = inputs.get(source)
        if artifact is None:
            continue
        data = stage.read_yaml(artifact)
        metrics = data.get("metrics") if isinstance(data, dict) else None
        require(isinstance(metrics, list), f"{source} metrics are unavailable")
        for metric in metrics:
            identifier = metric.get("id") if isinstance(metric, dict) else None
            require(isinstance(identifier, str), f"{source} has an invalid metric ID")
            values.add((source, identifier))
    return values


def yaml_bytes(value: dict[str, str]) -> bytes:
    encoded = subprocess.run(
        ["yq", "eval", "-p=json", "-o=yaml", "."], input=json.dumps(value).encode(), capture_output=True, check=False,
    )
    require(encoded.returncode == 0, "cannot encode disposition checkpoint")
    return encoded.stdout


def write_records(
    root: Path, available: set[tuple[str, str]], kind: str, source: str, identifiers: list[str], reason_code: str | None = None, reason: str | None = None,
) -> list[Path]:
    require(kind in {"rejected", "not-considered"}, "disposition kind is invalid")
    require(source in {"application-metrics", "kubernetes-metrics"}, "source artifact is invalid")
    require(identifiers and len(identifiers) == len(set(identifiers)), "metric IDs must be unique")
    require(all((source, identifier) in available for identifier in identifiers), "metric ID is not in the ticketed shortlist")
    if kind == "rejected":
        require(isinstance(reason_code, str) and IDENTIFIER_RE.fullmatch(reason_code) is not None, "reason code is invalid")
        require(isinstance(reason, str) and 0 < len(reason) <= 256 and reason.strip(), "reason is invalid")
    else:
        require(reason_code is None and reason is None, "not-considered records do not have a reason")
    root = root.resolve()
    for directory in (root / "records" / "rejected", root / "records" / "not-considered"):
        for identifier in identifiers:
            require(not (directory / f"{source}-{identifier}.yaml").exists(), f"metric already has a disposition: {identifier}")
    destination = root / "records" / kind
    destination.mkdir(parents=True, exist_ok=True)
    outputs = [destination / f"{source}-{identifier}.yaml" for identifier in identifiers]
    for identifier, output in zip(identifiers, outputs, strict=True):
        value = {"source_artifact": source, "metric_id": identifier}
        if kind == "rejected":
            value.update({"reason_code": reason_code, "reason": reason})
        content = yaml_bytes(value)
        with tempfile.NamedTemporaryFile("wb", dir=destination, prefix=f".{identifier}.", delete=False) as draft:
            draft_path = Path(draft.name)
            draft.write(content)
        os.replace(draft_path, output)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    commands = parser.add_subparsers(dest="kind", required=True)
    for kind in ("rejected", "not-considered"):
        command = commands.add_parser(kind)
        command.add_argument("source", choices=("application-metrics", "kubernetes-metrics"))
        command.add_argument("--metric-id", dest="identifiers", action="append", required=True)
        if kind == "rejected":
            command.add_argument("--reason-code", required=True)
            command.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        ticket, _, _, _, inputs, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "metrics-reviewer", "ticket is not for metrics-reviewer")
        outputs = write_records(
            args.ticket.parent.parent, source_ids(inputs), args.kind, args.source, args.identifiers,
            getattr(args, "reason_code", None), getattr(args, "reason", None),
        )
    except (OSError, DispositionError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL metric-disposition: {error}", file=sys.stderr)
        return 1
    print(f"PASS metric-disposition kind={args.kind} records={len(outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
