"""Native-only subprocess entry point for bounded Project COM operations.

This process deliberately has no oracle/comparison operation.  Oracle release
is owned by a separate process after the parent has verified the complete
observation freeze gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from deterministic_scheduling_core.provenance import (
    canonical_json as canonical_json_module,
)

from . import headless as headless_core
from . import headless_com as com_backend
from .headless import (
    durable_write_canonical_json,
    load_source_only_projection_with_identity,
)
from .headless_com import (
    capture_environment,
    failure_record,
    run_calendar_characterisation,
    run_native_case,
    run_preflight,
)


class StageJournal:
    def __init__(self, state_path: Path, log_path: Path):
        self.state_path = state_path
        self.log_path = log_path
        self.sequence = 0

    def __call__(self, stage: str, phase: str, details: Mapping[str, Any]) -> None:
        self.sequence += 1
        event = {
            "sequence": self.sequence,
            "worker_pid": os.getpid(),
            "stage": stage,
            "phase": phase,
            "details": dict(details),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        data = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.replace(temporary, self.state_path)
                break
            except PermissionError:
                # Windows readers do not request delete sharing by default, so
                # a watchdog read can briefly block the atomic replacement.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _automation_source_hashes(repository_root: Path) -> dict[str, str]:
    paths = {
        "automation_tool_sha256": repository_root
        / "tools"
        / "run_msproject_headless_relationship_characterisation.py",
        "headless_core_sha256": Path(headless_core.__file__).resolve(),
        "headless_com_sha256": Path(com_backend.__file__).resolve(),
        "headless_worker_sha256": Path(__file__).resolve(),
        "canonical_json_sha256": Path(canonical_json_module.__file__).resolve(),
        # The parent executes freeze.py when authenticating the worker's bounded
        # result and journal snapshots.  Bind those exact source bytes here
        # without importing freeze (which deliberately remains oracle-capable).
        "freeze_sha256": repository_root
        / "src"
        / "deterministic_scheduling_core"
        / "native"
        / "msproject"
        / "freeze.py",
    }
    return {role: _sha256_file(path) for role, path in paths.items()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--worker",
        dest="operation",
        choices=("environment", "preflight", "case", "calendar"),
        help="internal native worker mode",
    )
    operation.add_argument(
        "--operation",
        dest="operation",
        choices=("environment", "preflight", "case", "calendar"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--case")
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    if args.operation == "case" and not args.case:
        _parser().error("--case is required for the case worker")
    if args.operation != "case" and args.case:
        _parser().error("--case is valid only for the case worker")
    journal = StageJournal(args.state, args.log)
    journal(
        "worker",
        "start",
        {"operation": args.operation, "run_id": args.run_id, "case_id": args.case},
    )
    try:
        if args.operation == "environment":
            result = capture_environment(journal)
        elif args.operation == "preflight":
            result = run_preflight(args.workspace, journal)
        elif args.operation == "case":
            automation_hashes = _automation_source_hashes(
                args.repository_root.resolve()
            )
            projection, source_digest = load_source_only_projection_with_identity(
                args.repository_root, args.case
            )
            result = run_native_case(projection, args.workspace, journal)
            if not isinstance(result, Mapping):
                raise TypeError("native case worker result must be an object")
            result = dict(result)
            existing_digest = result.get("source_projection_sha256")
            if existing_digest not in (None, source_digest):
                raise ValueError("native backend returned a conflicting source digest")
            result["source_projection_sha256"] = source_digest
            existing_hashes = result.get("automation_source_hashes")
            if existing_hashes not in (None, automation_hashes):
                raise ValueError(
                    "native backend returned conflicting automation source hashes"
                )
            result["automation_source_hashes"] = automation_hashes
            if result.get("schema_version") not in {
                "headless-msproject-native-observation-v0.1",
                "headless-msproject-native-observation-v0.2",
            }:
                raise ValueError("native backend returned an unsupported observation schema")
            result["schema_version"] = "headless-msproject-native-observation-v0.2"
        else:
            result = run_calendar_characterisation(args.workspace, journal)
        digest = durable_write_canonical_json(args.result, result)
        journal("worker", "complete", {"operation": args.operation, "result_sha256": digest})
        return 0
    except BaseException as error:
        record = failure_record(error)
        failure_path = args.workspace / "worker-failure.json"
        try:
            durable_write_canonical_json(failure_path, record)
        except Exception:
            pass
        journal(
            "worker",
            "error",
            {
                "operation": args.operation,
                "error_type": type(error).__name__,
                "error": str(error),
                "failure_path": str(failure_path),
            },
        )
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
