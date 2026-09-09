#!/usr/bin/env python3
"""Stream Prometheus/OpenMetrics text from stdin into small YAML family snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


METADATA_RE = re.compile(r"^#\s+(HELP|TYPE|UNIT)\s+(.+)$")
TYPE_SUFFIXES = {
    "counter": ("_total", "_created"),
    "histogram": ("_bucket", "_sum", "_count", "_created"),
    "gaugehistogram": ("_bucket", "_gsum", "_gcount"),
    "summary": ("_sum", "_count", "_created"),
    "info": ("_info",),
}
MAX_RECORD_BYTES = 8192
MAX_MEMBERS = 64
MAX_LABELS = 64
MAX_WARNINGS = 16
MAX_LINE_CHARACTERS = 1024 * 1024


class SnapshotError(ValueError):
    pass


def require_yq_v4() -> None:
    try:
        result = subprocess.run(
            ["yq", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise SnapshotError("Mike Farah yq v4 is required") from error
    if (
        result.returncode != 0
        or "mikefarah/yq" not in result.stdout
        or "version v4." not in result.stdout
    ):
        raise SnapshotError("Mike Farah yq v4 is required")


@dataclass
class Family:
    name: str
    declared_type: str = "unknown"
    help: str | None = None
    unit: str | None = None
    members: set[str] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    sample_count: int = 0
    first_sample_line: int | None = None
    last_sample_line: int | None = None
    has_timestamps: bool = False
    has_exemplars: bool = False
    warnings: list[str] = field(default_factory=list)

    def warn(self, warning: str) -> None:
        if warning not in self.warnings and len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(warning)


def unescape(value: str) -> str:
    result: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            result.append("\n" if char == "n" else char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def name_and_rest(value: str) -> tuple[str, str]:
    value = value.lstrip()
    if not value:
        raise SnapshotError("missing metric name")
    if value[0] not in {'"', "`"}:
        parts = value.split(None, 1)
        return parts[0], parts[1] if len(parts) == 2 else ""
    quote = value[0]
    escaped = False
    for index in range(1, len(value)):
        char = value[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return unescape(value[1:index]), value[index + 1:].lstrip()
    raise SnapshotError("unterminated quoted metric name")


def split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "`"}:
            quote = char
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return [part.strip() for part in parts if part.strip()]


def sample_head_and_rest(line: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char.isspace() and depth == 0:
            return line[:index], line[index:].strip()
    raise SnapshotError("sample has no value")


def metric_and_labels(head: str) -> tuple[str, set[str]]:
    labels: set[str] = set()
    if head.startswith("{"):
        if not head.endswith("}"):
            raise SnapshotError("unterminated quoted metric/label set")
        parts = split_top_level(head[1:-1])
        if not parts or "=" in parts[0]:
            raise SnapshotError("quoted metric form has no metric name")
        name, rest = name_and_rest(parts[0])
        if rest:
            raise SnapshotError("invalid quoted metric name")
        label_parts = parts[1:]
    else:
        brace = head.find("{")
        if brace < 0:
            name = head
            label_parts = []
        else:
            if not head.endswith("}"):
                raise SnapshotError("unterminated label set")
            name = head[:brace]
            label_parts = split_top_level(head[brace + 1:-1])
    if not name:
        raise SnapshotError("empty metric name")
    for part in label_parts:
        if "=" not in part:
            raise SnapshotError("invalid label pair")
        raw_name = part.split("=", 1)[0].strip()
        label_name, rest = name_and_rest(raw_name)
        if rest:
            raise SnapshotError("invalid label name")
        labels.add(label_name)
    return name, labels


def value_tail(rest: str) -> str:
    if not rest:
        raise SnapshotError("sample has no value")
    if rest[0] != "{":
        parts = rest.split(None, 1)
        return parts[1] if len(parts) == 2 else ""
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(rest):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return rest[index + 1:].strip()
    raise SnapshotError("unterminated structured sample value")


def set_metadata(family: Family, kind: str, value: str) -> None:
    if kind == "TYPE":
        normalized = value.strip().lower()
        if family.declared_type != "unknown" and family.declared_type != normalized:
            family.warn("conflicting TYPE metadata")
        family.declared_type = normalized
    elif kind == "HELP":
        decoded = unescape(value)
        if len(decoded) > 512:
            decoded = decoded[:512]
            family.warn("HELP metadata truncated to 512 characters")
        if family.help is not None and family.help != decoded:
            family.warn("conflicting HELP metadata")
        family.help = decoded
    else:
        decoded = unescape(value)
        if len(decoded) > 128:
            decoded = decoded[:128]
            family.warn("UNIT metadata truncated to 128 characters")
        if family.unit is not None and family.unit != decoded:
            family.warn("conflicting UNIT metadata")
        family.unit = decoded


def aliases_for(family: Family) -> set[str]:
    aliases = {family.name}
    for suffix in TYPE_SUFFIXES.get(family.declared_type, ()):
        if not family.name.endswith(suffix):
            aliases.add(family.name + suffix)
    return aliases


def resolve_family(sample_name: str, families: dict[str, Family]) -> Family:
    if sample_name in families:
        return families[sample_name]
    matches = [family for family in families.values() if sample_name in aliases_for(family)]
    if len(matches) == 1:
        return matches[0]
    family = families.setdefault(sample_name, Family(sample_name))
    if len(matches) > 1:
        family.warn("sample member matches multiple declared families")
    return family


def yaml_bytes(record: dict[str, object]) -> bytes:
    try:
        result = subprocess.run(
            ["yq", "eval", "-p=json", "-o=yaml", "."],
            input=json.dumps(record, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise SnapshotError("Mike Farah yq v4 is required") from error
    if result.returncode != 0:
        raise SnapshotError("yq failed to encode a snapshot record")
    if len(result.stdout) > MAX_RECORD_BYTES:
        raise SnapshotError("snapshot record exceeds 8192 bytes")
    return result.stdout


def write_snapshots(
    output_dir: Path,
    families: dict[str, Family],
    source_ref: str,
    line_count: int,
    parse_warnings: list[dict[str, object]],
) -> None:
    if output_dir.exists():
        raise SnapshotError("output directory already exists")
    if not output_dir.parent.is_dir() or output_dir.parent.is_symlink():
        raise SnapshotError("output directory parent must be an existing regular directory")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        for position, family_name in enumerate(sorted(families), start=1):
            family = families[family_name]
            members = sorted(family.members)
            labels = sorted(family.labels)
            if len(members) > MAX_MEMBERS:
                members = members[:MAX_MEMBERS]
                family.warn("member names truncated to 64 entries")
            if len(labels) > MAX_LABELS:
                labels = labels[:MAX_LABELS]
                family.warn("label names truncated to 64 entries")
            record = {
                "schema_version": 1,
                "kind": "metric-family-snapshot",
                "id": f"F{position:05d}",
                "family": family.name,
                "declared_type": family.declared_type,
                "unit": family.unit,
                "help": family.help,
                "members": members,
                "observed_labels": labels,
                "sample_count": family.sample_count,
                "first_sample_line": family.first_sample_line,
                "last_sample_line": family.last_sample_line,
                "has_timestamps": family.has_timestamps,
                "has_exemplars": family.has_exemplars,
                "source_ref": source_ref,
                "warnings": family.warnings,
            }
            (temporary / f"F{position:05d}.yaml").write_bytes(yaml_bytes(record))
        manifest = {
            "schema_version": 1,
            "kind": "metric-snapshot-manifest",
            "source_ref": source_ref,
            "line_count": line_count,
            "family_count": len(families),
            "parse_warnings": parse_warnings,
        }
        (temporary / "manifest.yaml").write_bytes(yaml_bytes(manifest))
        os.rename(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_stream(max_families: int) -> tuple[dict[str, Family], int, list[dict[str, object]]]:
    families: dict[str, Family] = {}
    parse_warnings: list[dict[str, object]] = []
    line_count = 0
    for line_count, raw_line in enumerate(sys.stdin, start=1):
        if len(raw_line) > MAX_LINE_CHARACTERS:
            raise SnapshotError("exposition line exceeds 1048576 characters")
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        metadata = METADATA_RE.match(line)
        if metadata:
            kind, payload = metadata.groups()
            try:
                name, value = name_and_rest(payload)
                family = families.setdefault(name, Family(name))
                set_metadata(family, kind, value)
            except SnapshotError as error:
                if len(parse_warnings) < MAX_WARNINGS:
                    parse_warnings.append({"line": line_count, "reason": str(error)})
            if len(families) > max_families:
                raise SnapshotError(f"family count exceeds configured maximum {max_families}")
            continue
        if line.startswith("#"):
            continue
        try:
            head, rest = sample_head_and_rest(line)
            sample_name, labels = metric_and_labels(head)
            family = resolve_family(sample_name, families)
            family.members.add(sample_name)
            family.labels.update(labels)
            family.sample_count += 1
            family.first_sample_line = family.first_sample_line or line_count
            family.last_sample_line = line_count
            tail = value_tail(rest)
            family.has_exemplars = family.has_exemplars or "#" in tail
            timestamp_part = tail.split("#", 1)[0].strip()
            family.has_timestamps = family.has_timestamps or bool(timestamp_part)
        except SnapshotError as error:
            if len(parse_warnings) < MAX_WARNINGS:
                parse_warnings.append({"line": line_count, "reason": str(error)})
        if len(families) > max_families:
            raise SnapshotError(f"family count exceeds configured maximum {max_families}")
    return families, line_count, parse_warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-ref", default="stdin", help="neutral evidence reference")
    parser.add_argument("--max-families", type=int, default=10000)
    args = parser.parse_args()
    try:
        if not 1 <= args.max_families <= 100000:
            raise SnapshotError("max-families must be between 1 and 100000")
        if len(args.source_ref) > 512:
            raise SnapshotError("source-ref exceeds 512 characters")
        require_yq_v4()
        families, line_count, warnings = parse_stream(args.max_families)
        if not families:
            raise SnapshotError("stdin contained no metric families")
        write_snapshots(args.output_dir, families, args.source_ref, line_count, warnings)
    except (OSError, SnapshotError, UnicodeError) as error:
        print(f"ERROR metric-snapshot: {error}", file=sys.stderr)
        return 1
    print(f"PASS metric-snapshot families={len(families)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
