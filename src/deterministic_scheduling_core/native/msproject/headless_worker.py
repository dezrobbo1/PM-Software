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
import stat
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


MAX_IMPORTED_CANONICAL_JSON_BYTES = 1024 * 1024


def _source_path_component_is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    if os.name == "nt":
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(reparse_flag and attributes & reparse_flag)
    return False


def _reject_source_link_components(path: Path, *, label: str) -> None:
    absolute = path.absolute()
    if any(
        _source_path_component_is_link(component)
        for component in (absolute, *absolute.parents)
    ):
        raise ValueError(
            f"{label} path must not contain symbolic links, junctions, or "
            "reparse points"
        )


def _stable_source_snapshot(
    path: Path, *, label: str, max_bytes: int
) -> tuple[bytes, str]:
    """Read one bounded regular source file without following a final link."""

    _reject_source_link_components(path, label=label)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if before.st_size > max_bytes:
            raise ValueError(f"{label} exceeds its {max_bytes}-byte limit")
        chunks: list[bytes] = []
        observed_size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            observed_size += len(block)
            if observed_size > max_bytes:
                raise ValueError(f"{label} exceeds its {max_bytes}-byte limit")
            chunks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.stat(path, follow_symlinks=False)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise ValueError(f"{label} changed while it was read")
    if any(getattr(after, field) != getattr(current, field) for field in stable_fields):
        raise ValueError(f"{label} was replaced while it was read")
    data = b"".join(chunks)
    if len(data) != after.st_size:
        raise ValueError(f"{label} byte count changed while it was read")
    _reject_source_link_components(path, label=label)
    return data, hashlib.sha256(data).hexdigest()


try:
    _canonical_json_file = getattr(canonical_json_module, "__file__", None)
    if not isinstance(_canonical_json_file, str):
        raise OSError("canonical_json module has no source path")
    _IMPORTED_CANONICAL_JSON_LEXICAL_PATH = Path(
        _canonical_json_file
    ).absolute()
    _reject_source_link_components(
        _IMPORTED_CANONICAL_JSON_LEXICAL_PATH,
        label="imported native-worker canonical_json source",
    )
    _IMPORTED_CANONICAL_JSON_PATH = (
        _IMPORTED_CANONICAL_JSON_LEXICAL_PATH.resolve(strict=True)
    )
    (
        _IMPORTED_CANONICAL_JSON_BYTES,
        _IMPORTED_CANONICAL_JSON_SHA256,
    ) = _stable_source_snapshot(
        _IMPORTED_CANONICAL_JSON_PATH,
        label="imported native-worker canonical_json source",
        max_bytes=MAX_IMPORTED_CANONICAL_JSON_BYTES,
    )
    _reject_source_link_components(
        _IMPORTED_CANONICAL_JSON_LEXICAL_PATH,
        label="imported native-worker canonical_json source",
    )
except (OSError, ValueError) as error:
    raise ImportError(
        "native worker canonical_json source identity cannot be captured at import"
    ) from error


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
    }
    canonical_json_path = (
        repository_root
        / "src"
        / "deterministic_scheduling_core"
        / "provenance"
        / "canonical_json.py"
    )
    current_module_file = getattr(canonical_json_module, "__file__", None)
    try:
        if not isinstance(current_module_file, str):
            raise ValueError(
                "executed canonical_json module has no source path"
            )
        current_lexical_path = Path(current_module_file).absolute()
        _reject_source_link_components(
            current_lexical_path,
            label="executed native-worker canonical_json module",
        )
        _reject_source_link_components(
            canonical_json_path,
            label="checked-out native-worker canonical_json source",
        )
        if (
            current_lexical_path != _IMPORTED_CANONICAL_JSON_LEXICAL_PATH
            or current_lexical_path.resolve(strict=True)
            != _IMPORTED_CANONICAL_JSON_PATH
            or canonical_json_path.resolve(strict=True)
            != _IMPORTED_CANONICAL_JSON_PATH
        ):
            raise ValueError(
                "executed canonical_json module is not the captured "
                "checked-out source"
            )
        canonical_json_bytes, canonical_json_sha256 = _stable_source_snapshot(
            canonical_json_path,
            label="current native-worker canonical_json source",
            max_bytes=MAX_IMPORTED_CANONICAL_JSON_BYTES,
        )
    except OSError as error:
        raise ValueError(
            "native-worker canonical_json source path cannot be revalidated"
        ) from error
    if (
        canonical_json_sha256 != _IMPORTED_CANONICAL_JSON_SHA256
        or canonical_json_bytes != _IMPORTED_CANONICAL_JSON_BYTES
    ):
        raise ValueError(
            "canonical_json source changed after the native worker imported it"
        )

    # The parent executes freeze.py when authenticating the worker's bounded
    # result and journal snapshots. Bind a stable snapshot of those exact
    # source bytes here without importing the oracle-capable module.
    freeze_path = (
        repository_root
        / "src"
        / "deterministic_scheduling_core"
        / "native"
        / "msproject"
        / "freeze.py"
    )
    _freeze_bytes, freeze_sha256 = _stable_source_snapshot(
        freeze_path,
        label="non-imported parent freeze source",
        max_bytes=MAX_IMPORTED_CANONICAL_JSON_BYTES,
    )
    return {
        **{role: _sha256_file(path) for role, path in paths.items()},
        "canonical_json_sha256": _IMPORTED_CANONICAL_JSON_SHA256,
        "freeze_sha256": freeze_sha256,
    }


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
    case_automation_hashes: dict[str, str] | None = None
    try:
        if args.operation == "environment":
            result = capture_environment(journal)
        elif args.operation == "preflight":
            result = run_preflight(args.workspace, journal)
        elif args.operation == "case":
            case_automation_hashes = _automation_source_hashes(
                args.repository_root.resolve()
            )
            projection, source_digest = load_source_only_projection_with_identity(
                args.repository_root, args.case
            )
            result = run_native_case(projection, args.workspace, journal)
            if (
                _automation_source_hashes(args.repository_root.resolve())
                != case_automation_hashes
            ):
                raise ValueError(
                    "automation source identities changed during native case execution"
                )
            if not isinstance(result, Mapping):
                raise TypeError("native case worker result must be an object")
            result = dict(result)
            existing_digest = result.get("source_projection_sha256")
            if existing_digest not in (None, source_digest):
                raise ValueError("native backend returned a conflicting source digest")
            result["source_projection_sha256"] = source_digest
            existing_hashes = result.get("automation_source_hashes")
            if existing_hashes not in (None, case_automation_hashes):
                raise ValueError(
                    "native backend returned conflicting automation source hashes"
                )
            result["automation_source_hashes"] = case_automation_hashes
            if result.get("schema_version") not in {
                "headless-msproject-native-observation-v0.1",
                "headless-msproject-native-observation-v0.2",
            }:
                raise ValueError("native backend returned an unsupported observation schema")
            result["schema_version"] = "headless-msproject-native-observation-v0.2"
        else:
            result = run_calendar_characterisation(args.workspace, journal)
        digest = durable_write_canonical_json(args.result, result)
        if (
            case_automation_hashes is not None
            and _automation_source_hashes(args.repository_root.resolve())
            != case_automation_hashes
        ):
            raise ValueError(
                "automation source identities changed while the native case "
                "result was serialized"
            )
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
