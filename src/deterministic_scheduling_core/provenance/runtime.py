from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

from deterministic_scheduling_core import (
    DETERMINISTIC_PROFILE,
    KERNEL_VERSION,
    OBJECTIVE_POLICY,
    SEMANTIC_PROFILE,
    __version__,
)


_EXPECTED_PROFILE: dict[str, Any] = {
    "profile_id": "deterministic-v0.2",
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
    "python_runtime": "CPython>=3.11",
    "execution_record_hash_projection": "canonical-record-with-executed_at-omitted",
    "evidence_path_policy": "repository-relative-posix",
    "supersedes": "deterministic-v0.1",
    "change_reason": "pin_canonical_serialisation_and_reference_kernel_before_first_phase1_execution",
}


def load_execution_profile(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "config" / "deterministic-execution-profile-v0.2.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile != _EXPECTED_PROFILE:
        raise ValueError("complete Phase 1 deterministic execution profile is not pinned")
    if platform.python_implementation() != "CPython" or sys.version_info < (3, 11):
        raise RuntimeError("deterministic-v0.2 requires CPython 3.11 or later")
    return profile


def execution_identity_document(
    *,
    schedule: dict[str, Any],
    input_hash: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "phase1-execution-identity-v0.1",
        "canonical_input_hash": input_hash,
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
        "execution_platform_fingerprint": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "byte_order": sys.byteorder,
        },
    }
