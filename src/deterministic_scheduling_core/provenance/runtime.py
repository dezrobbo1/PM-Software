from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
import platform
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from deterministic_scheduling_core import (
    DETERMINISTIC_PROFILE,
    KERNEL_VERSION,
    OBJECTIVE_POLICY,
    SEMANTIC_PROFILE,
    __version__,
)


_EXPECTED_PROFILE: dict[str, Any] = {
    "profile_id": "deterministic-v0.3",
    "canonical_json": "dsc-canonical-json-v1",
    "unicode_normalization": "NFC",
    "hash_algorithm": "SHA-256",
    "time_representation": "integer",
    "worker_count": 1,
    "random_seed": 0,
    "wall_clock_termination_for_semantic_tests": False,
    "solver_name": "standard-library-reference-cpm",
    "solver_build": "reference-cpm-kernel-v0.1.0",
    "tie_break_policy": "objective-v0.3-level-7",
    "cross_version_determinism_promised": False,
    "python_runtime": "CPython 3.11.x or 3.12.x on Linux x86_64",
    "dependency_lock_path": "requirements/phase1-ci.lock",
    "dependency_lock_sha256": "74b5ba48ac5fb911b95357f405f7086e6f36abdf9b544b73cc587efa4b39220d",
    "dependency_distributions": {
        "attrs": "26.1.0",
        "jsonschema": "4.26.0",
        "jsonschema-specifications": "2025.9.1",
        "referencing": "0.37.0",
        "rfc3339-validator": "0.1.4",
        "rpds-py": "2026.6.3",
        "setuptools": "80.9.0",
        "six": "1.17.0",
        "typing-extensions": "4.16.0",
    },
    "portable_semantic_result_projection": "phase1-portable-semantic-result-v0.1",
    "portable_failure_result_projection": "phase1-portable-failure-result-v0.1",
    "environment_evidence_projection": "phase1-environment-evidence-v0.1",
    "execution_record_hash_projection": "canonical-record-with-executed_at-omitted",
    "evidence_path_policy": "repository-relative-posix",
    "output_directory_owner_marker": ".dsc-phase1-output-owner.json",
    "supersedes": "deterministic-v0.2",
    "change_reason": "lock_the_phase1_evidence_dependency_closure_split_portable_results_from_environment_evidence_and_require_owned_output_directories",
}


_SOURCE_EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "native-files",
    "node_modules",
    "private-data",
    "results",
    "venv",
}
_SOURCE_EXCLUDED_DIRECTORY_SUFFIXES = (".egg-info",)
_SOURCE_EXCLUDED_FILE_NAMES = {".DS_Store", ".env", "manifest.sha256"}
_SOURCE_EXCLUDED_FILE_SUFFIXES = (".pyc",)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_source_paths(repository_root: Path) -> list[PurePosixPath]:
    """Return the explicit source-archive file set without consulting Git.

    The exclusions are deliberately closed and mirror repository-owned generated,
    private, and tool-cache locations. Every other regular file is source material
    and therefore must be present exactly once in ``manifest.sha256``. Symbolic
    links are not valid source entries because their archive extraction semantics
    are not portable.
    """

    paths: list[PurePosixPath] = []
    pending = [(repository_root, PurePosixPath())]
    while pending:
        directory, relative_directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = relative_directory / entry.name
                if entry.is_dir(follow_symlinks=False) and (
                    entry.name in _SOURCE_EXCLUDED_DIRECTORY_NAMES
                    or entry.name.endswith(_SOURCE_EXCLUDED_DIRECTORY_SUFFIXES)
                ):
                    continue
                if entry.is_file(follow_symlinks=False) and (
                    entry.name in _SOURCE_EXCLUDED_FILE_NAMES
                    or entry.name.endswith(_SOURCE_EXCLUDED_FILE_SUFFIXES)
                ):
                    continue
                if entry.is_symlink():
                    raise RuntimeError(
                        "source tree contains a symbolic link outside an excluded "
                        f"location: {relative.as_posix()}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append((Path(entry.path), relative))
                elif entry.is_file(follow_symlinks=False):
                    paths.append(relative)
                else:
                    raise RuntimeError(
                        "source tree contains a non-regular entry: "
                        f"{relative.as_posix()}"
                    )
    return sorted(paths, key=lambda item: item.as_posix())


def verified_source_manifest_hash(repository_root: Path) -> str:
    repository_root = repository_root.resolve()
    manifest = repository_root / "manifest.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("source manifest is missing")
    manifest_paths: list[PurePosixPath] = []
    seen_paths: set[PurePosixPath] = set()
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        expected, separator, raw_path = line.partition("  ")
        relative = PurePosixPath(raw_path)
        if (
            separator != "  "
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
            or relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or raw_path != relative.as_posix()
            or "\\" in raw_path
        ):
            raise RuntimeError(f"source manifest line {line_number} is invalid")
        if relative in seen_paths:
            raise RuntimeError(
                f"source manifest contains duplicate path {relative.as_posix()}"
            )
        seen_paths.add(relative)
        manifest_paths.append(relative)
        source_path = repository_root.joinpath(*relative.parts)
        if source_path.is_symlink() or not source_path.is_file():
            raise RuntimeError(
                f"source manifest path is not a regular file: {relative.as_posix()}"
            )
        if _sha256_file(source_path) != expected:
            raise RuntimeError(f"source manifest does not match {relative.as_posix()}")
    archive_paths = _archive_source_paths(repository_root)
    if manifest_paths != archive_paths:
        manifest_set = set(manifest_paths)
        archive_set = set(archive_paths)
        omitted = sorted(path.as_posix() for path in archive_set - manifest_set)
        extra = sorted(path.as_posix() for path in manifest_set - archive_set)
        out_of_order = not omitted and not extra
        details: list[str] = []
        if omitted:
            details.append("omitted: " + ", ".join(omitted))
        if extra:
            details.append("extra: " + ", ".join(extra))
        if out_of_order:
            details.append("entries are not in canonical path order")
        raise RuntimeError("source manifest inventory mismatch (" + "; ".join(details) + ")")
    return _sha256_file(manifest)


def _verified_locked_distributions(profile: dict[str, Any]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for name, expected in profile["dependency_distributions"].items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"deterministic-v0.3 dependency is not installed: {name}") from exc
        if actual != expected:
            raise RuntimeError(
                f"deterministic-v0.3 dependency mismatch for {name}: "
                f"expected {expected}, found {actual}"
            )
        verified[name] = actual
    return verified


def load_execution_profile(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "config" / "deterministic-execution-profile-v0.3.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile != _EXPECTED_PROFILE:
        raise ValueError("complete Phase 1 deterministic execution profile is not pinned")
    if (
        platform.python_implementation() != "CPython"
        or sys.version_info[:2] not in {(3, 11), (3, 12)}
        or platform.system() != "Linux"
        or platform.machine().lower() not in {"x86_64", "amd64"}
    ):
        raise RuntimeError(
            "deterministic-v0.3 requires CPython 3.11.x or 3.12.x on Linux x86_64"
        )
    lock_path = repository_root / profile["dependency_lock_path"]
    if not lock_path.is_file():
        raise RuntimeError("deterministic-v0.3 dependency lock is missing")
    if _sha256_file(lock_path) != profile["dependency_lock_sha256"]:
        raise RuntimeError("deterministic-v0.3 dependency lock hash does not match")
    _verified_locked_distributions(profile)
    return profile


def dependency_environment_document(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "phase1-dependency-environment-v0.1",
        "lock_path": profile["dependency_lock_path"],
        "lock_sha256": profile["dependency_lock_sha256"],
        "verified_locked_distributions": _verified_locked_distributions(profile),
        "scope": "locked_runtime_and_build_dependency_closure",
        "pip_version": metadata.version("pip"),
    }


def execution_identity_document(
    *,
    schedule: dict[str, Any],
    input_hash: str,
    profile: dict[str, Any],
    source_manifest_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": "phase1-execution-identity-v0.1",
        "canonical_input_hash": input_hash,
        "source_manifest_hash": source_manifest_hash,
        "source_snapshot_identifier": schedule.get("source_snapshot_id"),
        "canonical_schema_version": schedule["schema_version"],
        "semantic_profile": SEMANTIC_PROFILE,
        "application_version": __version__,
        "cpm_kernel_version": KERNEL_VERSION,
        "constraint_model_version": "not_applicable",
        "objective_policy": OBJECTIVE_POLICY,
        "deterministic_profile": profile["profile_id"],
        "canonical_json": profile["canonical_json"],
        "solver_name": profile["solver_name"],
        "solver_build": profile["solver_build"],
        "solver_parameters": {
            "worker_count": profile["worker_count"],
            "random_seed": profile["random_seed"],
            "wall_clock_termination": profile["wall_clock_termination_for_semantic_tests"],
        },
        "search_strategy": "none_except_complete_two-order_enumeration_for_preregistered_resource_cases",
        "time_or_branch_limit": None,
        "warm_start_identifier": None,
        "tie_break_policy": profile["tie_break_policy"],
        "dependency_environment": dependency_environment_document(profile),
        "execution_platform_fingerprint": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "byte_order": sys.byteorder,
        },
    }
