#!/usr/bin/env python3
"""Validate the bounded one-line response emitted by a dashboard specialist."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


RESPONSE_RE = re.compile(
    r"^(DONE|PASS|FAIL|BLOCKED) ([A-Za-z][A-Za-z0-9._-]{0,63}) "
    r"(artifact|report)=([^\s]{1,160}) sha256=(sha256:[0-9a-f]{64})$"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response_file", type=Path)
    args = parser.parse_args()
    try:
        raw = args.response_file.read_text(encoding="utf-8")
    except OSError:
        print("FAIL response file is unreadable", file=sys.stderr)
        return 1
    response = raw[:-1] if raw.endswith("\n") else raw
    if "\n" in response or len(response) > 256:
        print("FAIL stage response must be one line of at most 256 characters", file=sys.stderr)
        return 1
    match = RESPONSE_RE.fullmatch(response)
    if match is None:
        print("FAIL stage response does not match the required grammar", file=sys.stderr)
        return 1
    status, _, field, _, _ = match.groups()
    expected_field = "report" if status in {"FAIL", "BLOCKED"} else "artifact"
    if field != expected_field:
        print(f"FAIL {status} response must use {expected_field}=", file=sys.stderr)
        return 1
    print("PASS stage response")
    return 0


if __name__ == "__main__":
    sys.exit(main())
