"""Fail-closed evidence helpers for headless Microsoft Project characterisation.

This module is deliberately independent of the frozen manual-native evidence
track. Construction accepts only the operator-safe source projections. Sealed
reference access lives in the separately executable :mod:`headless_compare`
module and is not imported by native construction code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes


PILOT_ID = "microsoft-project-relationship-v0.1"
TRACK_ID = "headless_native_characterisation"
CASE_IDS = tuple(f"SEM-REL-{number:03d}" for number in range(1, 13))
SOURCE_DIRECTORY = PurePosixPath(
    "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
    "source-only-case-projections"
)
RAW_ROOT = PurePosixPath("native-files/headless-msproject-characterisation")
ORIGIN = "2026-01-05T08:00:00+08:00"
_CASE_RE = re.compile(r"^SEM-REL-(?:00[1-9]|01[0-2])$")
_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTOMATION_HASH_ROLES = frozenset(
    {
        "automation_tool_sha256",
        "headless_core_sha256",
        "headless_com_sha256",
        "headless_worker_sha256",
    }
)
_COMMON_SHARED_HASH_ROLES = _AUTOMATION_HASH_ROLES | frozenset(
    {"environment_sha256", "project_executable_sha256"}
)
_ALL_SHARED_HASH_ROLES = _COMMON_SHARED_HASH_ROLES | frozenset(
    {"source_only_projection_sha256"}
)
CASE_NATIVE_ARTIFACT_ROLES = frozenset(
    {"initial_mpp", "initial_xml", "reopened_mpp", "reopened_xml"}
)
CASE_SUPPORT_ARTIFACT_ROLES = frozenset(
    {
        "worker_result",
        "com_log",
        "stage_state",
        "worker_stdout",
        "worker_stderr",
    }
)
CASE_FROZEN_ARTIFACT_ROLES = (
    CASE_NATIVE_ARTIFACT_ROLES | CASE_SUPPORT_ARTIFACT_ROLES
)
CASE_ARTIFACT_FILENAMES = {
    "initial_mpp": "initial-calculated.mpp",
    "initial_xml": "initial-calculated.xml",
    "reopened_mpp": "reopened-recalculated.mpp",
    "reopened_xml": "reopened-recalculated.xml",
    "worker_result": "worker-native-result.json",
    "com_log": "case-com-log.jsonl",
    "stage_state": "case-stage-state.json",
    "worker_stdout": "case-worker-stdout.log",
    "worker_stderr": "case-worker-stderr.log",
}
_FORBIDDEN_SOURCE_KEYS = frozenset(
    {
        "expected",
        "expected_normalized",
        "activity_times",
        "project_finish",
        "total_float",
        "free_float",
        "driving_relationships",
        "resource_order",
        "assertions",
    }
)
CHARACTERISATION_STATUSES = frozenset(
    {"characterisation_exact", "characterisation_mismatch", "characterisation_inconclusive"}
)


class HeadlessCharacterisationError(RuntimeError):
    """Base error for the non-claim-eligible characterisation path."""


class SourceIsolationError(HeadlessCharacterisationError):
    """A construction input is outside the source-only boundary."""


class DurableEvidenceError(HeadlessCharacterisationError):
    """Evidence could not be durably created or verified."""


class ObservationFreezeError(HeadlessCharacterisationError):
    """The observation-before-oracle gate is incomplete or inconsistent."""


class OffGridTimestampError(HeadlessCharacterisationError):
    """A Project timestamp is not an exact canonical hour coordinate."""


class XmlObservationError(HeadlessCharacterisationError):
    """A Project-authored XML observation is malformed or unsafe."""


@dataclass(frozen=True)
class RunWorkspace:
    repository_root: Path
    run_id: str
    path: Path


@dataclass(frozen=True)
class CaseWorkspace:
    run: RunWorkspace
    case_id: str
    path: Path


@dataclass(frozen=True)
class FreezeVerification:
    case_id: str
    observation_sha256: str
    manifest_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise DurableEvidenceError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DurableEvidenceError(f"{label} must be a non-symlink regular file: {path}")


def _contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _FORBIDDEN_SOURCE_KEYS:
                return str(key)
            nested = _contains_forbidden_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _contains_forbidden_key(item)
            if nested:
                return nested
    return None


def source_projection_path(repository_root: Path, case_id: str) -> Path:
    if not _CASE_RE.fullmatch(case_id):
        raise SourceIsolationError(f"unsupported relationship case: {case_id!r}")
    return repository_root.joinpath(*SOURCE_DIRECTORY.parts, f"{case_id}.json")


def load_source_only_projection(
    repository_root: Path,
    case_id: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Load one exact source projection, rejecting fixture/control aliases."""

    payload, _digest = load_source_only_projection_with_identity(
        repository_root, case_id, path=path
    )
    return payload


def load_source_only_projection_with_identity(
    repository_root: Path,
    case_id: str,
    *,
    path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load and hash the exact same source bytes in one bounded read.

    Native callers must bind the returned digest into the worker result and
    re-check the on-disk source after the worker exits.
    """

    repository_root = repository_root.resolve()
    expected = source_projection_path(repository_root, case_id).resolve(strict=False)
    candidate = (path if path is not None else expected).resolve(strict=False)
    if candidate != expected:
        raise SourceIsolationError(
            "construction input must be the exact source-only projection path; "
            f"expected {expected}, received {candidate}"
        )
    try:
        relative = candidate.relative_to(repository_root).as_posix().lower()
    except ValueError as error:
        raise SourceIsolationError("construction input escapes the repository") from error
    if any(token in relative for token in ("benchmarks/semantic/cases", "sealed", "expected")):
        raise SourceIsolationError("oracle-bearing or full-fixture path rejected")
    _regular_file(candidate, label="source-only projection")
    try:
        source_bytes = candidate.read_bytes()
        payload = json.loads(source_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceIsolationError("source-only projection is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise SourceIsolationError("source-only projection must be a JSON object")
    forbidden = _contains_forbidden_key(payload)
    if forbidden:
        raise SourceIsolationError(f"source-only projection contains forbidden key {forbidden!r}")
    if payload.get("case_id") != case_id:
        raise SourceIsolationError("source-only projection case identity mismatch")
    if payload.get("pilot_id") != PILOT_ID:
        raise SourceIsolationError("source-only projection pilot identity mismatch")
    if payload.get("schema_version") != "microsoft-project-source-only-case-projection-v0.1":
        raise SourceIsolationError("unsupported source-only projection schema")
    if payload.get("document_type") != "microsoft_project_source_only_case_projection":
        raise SourceIsolationError("unexpected source-only projection document type")
    if payload.get("status") != "prepared_not_executed":
        raise SourceIsolationError("source-only projection is not in the frozen prepared state")
    contract = payload.get("projection_contract")
    if not isinstance(contract, dict) or (
        contract.get("construction_inputs_only") is not True
        or contract.get("oracle_content_included") is not False
        or contract.get("full_fixture_binding_included") is not False
    ):
        raise SourceIsolationError("source-only projection contract is not construction-only")
    facts = payload.get("source_facts")
    if not isinstance(facts, dict):
        raise SourceIsolationError("source facts are missing")
    axis = facts.get("time_axis")
    if not isinstance(axis, dict) or axis.get("origin") != ORIGIN or axis.get("unit") != "hour":
        raise SourceIsolationError("unexpected native time axis")
    activities = facts.get("activity_inputs")
    relationships = facts.get("relationship_inputs")
    calendars = facts.get("calendar_inputs")
    if not isinstance(activities, list) or len(activities) != 2:
        raise SourceIsolationError("relationship characterisation requires exactly two tasks")
    if [item.get("id") for item in activities if isinstance(item, dict)] != ["A", "B"]:
        raise SourceIsolationError("source task order/identity is not exactly A, B")
    if not isinstance(relationships, list) or len(relationships) != 1:
        raise SourceIsolationError("relationship characterisation requires exactly one link")
    relationship = relationships[0]
    if not isinstance(relationship, dict) or relationship.get("type") not in {"FS", "SS", "FF", "SF"}:
        raise SourceIsolationError("source relationship type is unsupported")
    if relationship.get("lag") not in {-2, 0, 2}:
        raise SourceIsolationError("source signed lag is outside the frozen matrix")
    if not isinstance(calendars, list) or calendars != [
        {"id": "CAL-24X7", "working_intervals": [[0, 400]]}
    ]:
        raise SourceIsolationError("source calendar is not the frozen CAL-24X7 realization")
    if facts.get("resource_inputs") != [] or facts.get("operational_constraint_inputs") != []:
        raise SourceIsolationError("unexpected resources or operational constraints")
    return payload, hashlib.sha256(source_bytes).hexdigest()


def create_run_workspace(repository_root: Path, run_id: str, *, resume: bool = False) -> RunWorkspace:
    if not _RUN_RE.fullmatch(run_id):
        raise DurableEvidenceError("run ID must contain only safe deterministic filename characters")
    repository_root = repository_root.resolve()
    root = repository_root.joinpath(*RAW_ROOT.parts)
    path = root / run_id
    if resume:
        if not path.is_dir() or path.is_symlink():
            raise DurableEvidenceError(f"resume run workspace is unavailable: {path}")
    else:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise DurableEvidenceError(f"run workspace already exists: {path}") from error
    return RunWorkspace(repository_root=repository_root, run_id=run_id, path=path)


def create_case_workspace(run: RunWorkspace, case_id: str, *, resume: bool = False) -> CaseWorkspace:
    if case_id not in CASE_IDS:
        raise DurableEvidenceError(f"unsupported case: {case_id}")
    path = run.path / "cases" / case_id
    if resume:
        if not path.is_dir() or path.is_symlink():
            raise DurableEvidenceError(f"case workspace is unavailable for resume: {path}")
    else:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise DurableEvidenceError(f"case workspace already exists: {path}") from error
    return CaseWorkspace(run=run, case_id=case_id, path=path)


def durable_write_bytes(path: Path, data: bytes) -> str:
    """Create, flush and verify immutable evidence bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise DurableEvidenceError(f"refusing to overwrite evidence: {path}") from error
    except OSError as error:
        raise DurableEvidenceError(f"durable evidence write failed for {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    observed = path.read_bytes()
    if observed != data:
        raise DurableEvidenceError(f"durable evidence readback mismatch: {path}")
    return hashlib.sha256(observed).hexdigest()


def durable_write_canonical_json(path: Path, value: Any) -> str:
    return durable_write_bytes(path, canonical_bytes(value) + b"\n")


def build_artifact_manifest(
    artifacts: Mapping[str, Path], *, root: Path | None = None
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for role in sorted(artifacts):
        path = Path(artifacts[role])
        _regular_file(path, label=f"artifact {role}")
        relative = path.name if root is None else path.resolve().relative_to(root.resolve()).as_posix()
        entries.append(
            {
                "role": role,
                "relative_path": relative,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": "headless-msproject-artifact-manifest-v0.1",
        "characterisation_label": TRACK_ID,
        "artifacts": entries,
    }


def write_artifact_manifest(path: Path, artifacts: Mapping[str, Path], *, root: Path) -> str:
    return durable_write_canonical_json(path, build_artifact_manifest(artifacts, root=root))


def verify_artifact_manifest(path: Path, *, root: Path) -> dict[str, Any]:
    _regular_file(path, label="artifact manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {
        "headless-msproject-artifact-manifest-v0.1",
        "headless-msproject-artifact-manifest-v0.2",
    }:
        raise DurableEvidenceError("unsupported artifact manifest schema")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise DurableEvidenceError("artifact manifest must contain a non-empty artifact list")
    roles: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise DurableEvidenceError("artifact manifest entry must be an object")
        role = entry.get("role")
        relative_text = entry.get("relative_path")
        byte_size = entry.get("byte_size")
        digest = entry.get("sha256")
        if not isinstance(role, str) or not role or role in roles:
            raise DurableEvidenceError(f"invalid or duplicate artifact role: {role!r}")
        if not isinstance(relative_text, str) or not relative_text or relative_text in paths:
            raise DurableEvidenceError(f"invalid or duplicate artifact path: {relative_text!r}")
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
            raise DurableEvidenceError(f"invalid artifact byte size for {role}")
        if not isinstance(digest, str) or not _HEX_RE.fullmatch(digest):
            raise DurableEvidenceError(f"invalid artifact digest for {role}")
        roles.add(role)
        paths.add(relative_text)
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise DurableEvidenceError("unsafe artifact manifest path")
        artifact = root.joinpath(*relative.parts)
        _regular_file(artifact, label=f"manifest artifact {entry.get('role')}")
        if artifact.stat().st_size != byte_size or sha256_file(artifact) != digest:
            raise DurableEvidenceError(f"artifact identity mismatch: {relative.as_posix()}")
    return manifest


def _validated_shared_hashes(
    manifest: Mapping[str, Any], workspace: CaseWorkspace
) -> dict[str, str]:
    shared = manifest.get("shared_hashes")
    if not isinstance(shared, Mapping) or set(shared) != _ALL_SHARED_HASH_ROLES:
        raise ObservationFreezeError(
            "case manifest shared hashes do not contain the exact required roles"
        )
    normalized: dict[str, str] = {}
    for role in sorted(_ALL_SHARED_HASH_ROLES):
        digest = shared.get(role)
        if not isinstance(digest, str) or not _HEX_RE.fullmatch(digest):
            raise ObservationFreezeError(f"case manifest has an invalid {role}")
        normalized[role] = digest

    environment_path = workspace.run.path / "environment.json"
    _regular_file(environment_path, label="shared environment capture")
    if sha256_file(environment_path) != normalized["environment_sha256"]:
        raise ObservationFreezeError("shared environment digest does not match its evidence")
    try:
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        executable_digest = environment["project_executable"]["sha256"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ObservationFreezeError("shared environment has no Project executable identity") from error
    if not isinstance(executable_digest, str) or executable_digest.lower() != normalized[
        "project_executable_sha256"
    ]:
        raise ObservationFreezeError("shared Project executable digest is inconsistent")

    _payload, current_source_digest = load_source_only_projection_with_identity(
        workspace.run.repository_root, workspace.case_id
    )
    if current_source_digest != normalized["source_only_projection_sha256"]:
        raise ObservationFreezeError("source-only projection changed after native construction")
    return normalized


def freeze_native_observation(
    workspace: CaseWorkspace,
    observation: Mapping[str, Any],
    artifacts: Mapping[str, Path],
    *,
    shared_hashes: Mapping[str, str],
) -> FreezeVerification:
    if observation.get("schema_version") != "headless-msproject-native-observation-v0.2":
        raise ObservationFreezeError(
            "new freezes require worker-bound native observation schema v0.2"
        )
    if observation.get("case_id") != workspace.case_id:
        raise ObservationFreezeError("observation case identity mismatch")
    if observation.get("characterisation_label") != TRACK_ID:
        raise ObservationFreezeError("observation lacks the non-claim characterisation label")
    if set(artifacts) != CASE_FROZEN_ARTIFACT_ROLES:
        raise ObservationFreezeError(
            "new freezes require the exact MPP, XML, worker and journal artifact roles"
        )
    expected_artifacts = {
        role: (workspace.path / filename).resolve(strict=False)
        for role, filename in CASE_ARTIFACT_FILENAMES.items()
    }
    if any(
        Path(artifacts[role]).resolve(strict=False) != expected_artifacts[role]
        for role in CASE_FROZEN_ARTIFACT_ROLES
    ):
        raise ObservationFreezeError(
            "new freeze artifacts do not use the deterministic case filenames"
        )
    reported_native = observation.get("artifacts")
    if (
        not isinstance(reported_native, Mapping)
        or set(reported_native) != CASE_NATIVE_ARTIFACT_ROLES
        or any(
            not isinstance(reported_native.get(role), str)
            or Path(str(reported_native[role])).resolve(strict=False)
            != expected_artifacts[role]
            for role in CASE_NATIVE_ARTIFACT_ROLES
        )
    ):
        raise ObservationFreezeError(
            "native observation does not bind the exact deterministic MPP/XML paths"
        )
    if "executed_pass" in json.dumps(observation, sort_keys=True):
        raise ObservationFreezeError("manual-track executed_pass is forbidden")
    if set(shared_hashes) != _ALL_SHARED_HASH_ROLES or any(
        not isinstance(value, str) or not _HEX_RE.fullmatch(value)
        for value in shared_hashes.values()
    ):
        raise ObservationFreezeError("exact valid shared provenance hashes are required")
    if observation.get("source_projection_sha256") != shared_hashes[
        "source_only_projection_sha256"
    ]:
        raise ObservationFreezeError(
            "worker source digest is absent or disagrees with prelaunch identity"
        )
    worker_automation = observation.get("automation_source_hashes")
    if not isinstance(worker_automation, Mapping) or {
        role: worker_automation.get(role) for role in _AUTOMATION_HASH_ROLES
    } != {role: shared_hashes[role] for role in _AUTOMATION_HASH_ROLES}:
        raise ObservationFreezeError(
            "worker automation identities disagree with prelaunch hashes"
        )
    observation_path = workspace.path / "native-observation.json"
    observation_sha = durable_write_canonical_json(observation_path, observation)
    manifest = build_artifact_manifest(
        {"native_observation": observation_path, **artifacts}, root=workspace.run.path
    )
    manifest.update(
        {
            "schema_version": "headless-msproject-artifact-manifest-v0.2",
            "case_id": workspace.case_id,
            "observation_frozen_before_oracle": True,
            "shared_hashes": dict(sorted(shared_hashes.items())),
        }
    )
    manifest_path = workspace.path / "case-manifest.json"
    manifest_sha = durable_write_canonical_json(manifest_path, manifest)
    durable_write_bytes(workspace.path / "native-observation.sha256", f"{observation_sha}\n".encode())
    durable_write_bytes(workspace.path / "case-manifest.sha256", f"{manifest_sha}\n".encode())
    # The freeze claim is made only after every artifact, manifest and sidecar
    # has been read back and re-hashed from durable storage.
    return verify_observation_freeze(workspace)


def verify_observation_freeze(workspace: CaseWorkspace) -> FreezeVerification:
    observation_path = workspace.path / "native-observation.json"
    manifest_path = workspace.path / "case-manifest.json"
    _regular_file(observation_path, label="native observation")
    _regular_file(manifest_path, label="case manifest")
    manifest = verify_artifact_manifest(manifest_path, root=workspace.run.path)
    if manifest.get("case_id") != workspace.case_id or manifest.get("observation_frozen_before_oracle") is not True:
        raise ObservationFreezeError("case manifest does not prove observation-before-oracle")
    shared_hashes = _validated_shared_hashes(manifest, workspace)
    try:
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationFreezeError("native observation is not valid UTF-8 JSON") from error
    if not isinstance(observation, Mapping):
        raise ObservationFreezeError("native observation must be an object")
    if observation.get("case_id") != workspace.case_id:
        raise ObservationFreezeError("native observation case identity mismatch")
    strong_manifest = (
        manifest.get("schema_version")
        == "headless-msproject-artifact-manifest-v0.2"
        or observation.get("schema_version")
        == "headless-msproject-native-observation-v0.2"
    )
    manifest_roles = {
        item.get("role")
        for item in manifest["artifacts"]
        if isinstance(item, Mapping)
    }
    if strong_manifest and manifest_roles != {
        "native_observation",
        *CASE_FROZEN_ARTIFACT_ROLES,
    }:
        raise ObservationFreezeError(
            "native observation manifest lacks exact required artifacts"
        )
    if strong_manifest:
        entries_by_role = {
            str(item["role"]): str(item["relative_path"])
            for item in manifest["artifacts"]
            if isinstance(item, Mapping)
        }
        expected_relative_paths = {
            role: (workspace.path / filename)
            .resolve(strict=False)
            .relative_to(workspace.run.path.resolve(strict=False))
            .as_posix()
            for role, filename in CASE_ARTIFACT_FILENAMES.items()
        }
        expected_relative_paths["native_observation"] = (
            observation_path.resolve(strict=False)
            .relative_to(workspace.run.path.resolve(strict=False))
            .as_posix()
        )
        if entries_by_role != expected_relative_paths:
            raise ObservationFreezeError(
                "native observation manifest paths are not the deterministic case artifacts"
            )
        reported_native = observation.get("artifacts")
        if (
            not isinstance(reported_native, Mapping)
            or set(reported_native) != CASE_NATIVE_ARTIFACT_ROLES
            or any(
                not isinstance(reported_native.get(role), str)
                or Path(str(reported_native[role])).resolve(strict=False)
                != (workspace.path / CASE_ARTIFACT_FILENAMES[role]).resolve(
                    strict=False
                )
                for role in CASE_NATIVE_ARTIFACT_ROLES
            )
        ):
            raise ObservationFreezeError(
                "native observation MPP/XML paths disagree with its manifest"
            )
    source_binding = observation.get("source_projection_sha256")
    worker_automation = observation.get("automation_source_hashes")
    if strong_manifest or source_binding is not None:
        if source_binding != shared_hashes["source_only_projection_sha256"]:
            raise ObservationFreezeError(
                "native observation does not bind the parsed source bytes"
            )
    if strong_manifest or worker_automation is not None:
        if not isinstance(worker_automation, Mapping) or {
            role: worker_automation.get(role) for role in _AUTOMATION_HASH_ROLES
        } != {role: shared_hashes[role] for role in _AUTOMATION_HASH_ROLES}:
            raise ObservationFreezeError(
                "native observation does not bind the executed automation sources"
            )
    observation_sha = sha256_file(observation_path)
    entry = next(
        (item for item in manifest["artifacts"] if item.get("role") == "native_observation"),
        None,
    )
    if entry is None or entry.get("sha256") != observation_sha:
        raise ObservationFreezeError("native observation is not hash-bound by the case manifest")
    recorded = (workspace.path / "native-observation.sha256").read_text(encoding="ascii").strip()
    if recorded != observation_sha:
        raise ObservationFreezeError("native observation sidecar digest mismatch")
    manifest_sha = sha256_file(manifest_path)
    if (workspace.path / "case-manifest.sha256").read_text(encoding="ascii").strip() != manifest_sha:
        raise ObservationFreezeError("case manifest sidecar digest mismatch")
    return FreezeVerification(workspace.case_id, observation_sha, manifest_sha)


def verify_run_freeze_gate(
    run: RunWorkspace,
    *,
    write_index: bool = False,
    allow_legacy_stop_evidence_for_audit: bool = False,
) -> dict[str, Any]:
    """Verify all freezes and keep oracle authorization closed on any stop.

    ``allow_legacy_stop_evidence_for_audit`` exists only so post-run governance
    tooling can authenticate immutable v0.1 bytes whose historic index already
    made an incorrect oracle-permission claim. It must never be used by native
    execution or comparison code.
    """

    if write_index and allow_legacy_stop_evidence_for_audit:
        raise ObservationFreezeError(
            "legacy stop-evidence audit override is read-only and cannot write an index"
        )

    freezes: list[dict[str, str]] = []
    common_hashes: dict[str, str] | None = None
    for case_id in CASE_IDS:
        try:
            workspace = create_case_workspace(run, case_id, resume=True)
            verified = verify_observation_freeze(workspace)
        except (DurableEvidenceError, ObservationFreezeError) as error:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} is not durably frozen"
            ) from error
        manifest = json.loads(
            (workspace.path / "case-manifest.json").read_text(encoding="utf-8")
        )
        observation = json.loads(
            (workspace.path / "native-observation.json").read_text(encoding="utf-8")
        )
        try:
            retained_stops = effective_stop_conditions(observation)
        except ObservationFreezeError as error:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} stop evidence is malformed"
            ) from error
        if retained_stops and not allow_legacy_stop_evidence_for_audit:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} contains stop conditions: {retained_stops}"
            )
        shared = _validated_shared_hashes(manifest, workspace)
        candidate_common = {role: shared[role] for role in _COMMON_SHARED_HASH_ROLES}
        if common_hashes is None:
            common_hashes = candidate_common
        elif candidate_common != common_hashes:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} shared provenance differs across cases"
            )
        freezes.append(
            {
                "case_id": case_id,
                "native_observation_sha256": verified.observation_sha256,
                "case_manifest_sha256": verified.manifest_sha256,
            }
        )
    index = {
        "schema_version": "headless-msproject-observation-freeze-index-v0.1",
        "characterisation_label": TRACK_ID,
        "run_id": run.run_id,
        "oracle_access_permitted_after_this_freeze": True,
        "case_freezes": freezes,
    }
    path = run.path / "observation-freeze-index.json"
    if write_index:
        digest = durable_write_canonical_json(path, index)
        durable_write_bytes(run.path / "observation-freeze-index.sha256", f"{digest}\n".encode())
    else:
        _regular_file(path, label="observation freeze index")
        if json.loads(path.read_text(encoding="utf-8")) != index:
            raise ObservationFreezeError("run freeze index content mismatch")
        digest = sha256_file(path)
        if (run.path / "observation-freeze-index.sha256").read_text(encoding="ascii").strip() != digest:
            raise ObservationFreezeError("run freeze index digest mismatch")
    return index


def effective_stop_conditions(
    observation: Mapping[str, Any],
) -> list[Any]:
    """Return explicit and legacy-derived conditions that keep the oracle closed.

    Retained v0.1 observations could record an empty ``stop_conditions`` list
    even when a process session was forcibly terminated or had not exited.  The
    process-session facts are therefore authoritative stop evidence in every
    schema version, independent of the explicit list.
    """

    explicit = observation.get("stop_conditions")
    if not isinstance(explicit, list):
        raise ObservationFreezeError(
            "native observation lacks an explicit stop_conditions list"
        )
    conditions = list(explicit)
    sessions = observation.get("process_sessions")
    if sessions is None:
        return conditions
    if not isinstance(sessions, list):
        raise ObservationFreezeError("native observation process_sessions is malformed")
    strict_cleanup_identity = (
        observation.get("schema_version")
        == "headless-msproject-native-observation-v0.2"
    )
    for index, session in enumerate(sessions):
        if not isinstance(session, Mapping):
            raise ObservationFreezeError(
                "native observation process session is malformed"
            )
        identity = {
            "derived_from": "process_sessions",
            "process_session_index": index,
        }
        pid = session.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            identity["pid"] = pid
        if session.get("forced_termination") is True:
            conditions.append(
                {"condition": "forced_termination", **identity}
            )
        if session.get("exited") is not True:
            conditions.append(
                {"condition": "project_process_exit_not_confirmed", **identity}
            )
        ownership_retained = "ownership_revalidated_before_quit" in session
        if (strict_cleanup_identity or ownership_retained) and session.get(
            "ownership_revalidated_before_quit"
        ) is not True:
            conditions.append(
                {
                    "condition": "project_process_ownership_not_revalidated",
                    **identity,
                }
            )
        if session.get("termination_error") not in (None, ""):
            conditions.append(
                {"condition": "project_process_cleanup_error", **identity}
            )
    return conditions


def _iso_hour_coordinate(value: Any, *, origin: str = ORIGIN) -> int:
    if not isinstance(value, str):
        raise OffGridTimestampError(f"native timestamp must be an ISO string, got {type(value).__name__}")
    try:
        timestamp = datetime.fromisoformat(value)
        origin_value = datetime.fromisoformat(origin)
    except ValueError as error:
        raise OffGridTimestampError(f"invalid ISO timestamp: {value!r}") from error
    if timestamp.tzinfo is None or origin_value.tzinfo is None:
        raise OffGridTimestampError("native timestamp must contain an explicit local offset")
    seconds = Decimal(str((timestamp - origin_value).total_seconds()))
    coordinate = seconds / Decimal(3600)
    if coordinate != coordinate.to_integral_value():
        raise OffGridTimestampError(f"native timestamp is off the exact hour grid: {value}")
    return int(coordinate)


def normalize_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    calculated = observation.get("initial_calculated", observation)
    if not isinstance(calculated, Mapping):
        raise ObservationFreezeError("native observation has no initial calculation payload")
    tasks = calculated.get("tasks")
    project = calculated.get("project")
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)) or not isinstance(project, Mapping):
        raise ObservationFreezeError("native observation lacks calculated tasks/project")
    activities: dict[str, dict[str, int]] = {}
    names: list[str] = []
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ObservationFreezeError("native task observation is malformed")
        activity_id = task.get("name")
        if not isinstance(activity_id, str):
            raise ObservationFreezeError("native task name must be a string")
        names.append(activity_id)
        if activity_id not in {"A", "B"}:
            raise ObservationFreezeError(f"unexpected native task {activity_id!r}")
        if activity_id in activities:
            raise ObservationFreezeError(f"duplicate native task {activity_id!r}")
        activities[activity_id] = {
            "start": _iso_hour_coordinate(task.get("start")),
            "finish": _iso_hour_coordinate(task.get("finish")),
        }
    if sorted(names) != ["A", "B"]:
        raise ObservationFreezeError(
            "native observation must contain exactly one task A and one task B"
        )
    return {
        "case_id": observation.get("case_id"),
        "activities": activities,
        "project_finish": _iso_hour_coordinate(project.get("finish")),
        "extra_native_tasks": [],
    }


def _safe_xml_root(path: Path) -> tuple[ET.Element, str]:
    _regular_file(path, label="Project XML")
    data = path.read_bytes()
    if len(data) > 25 * 1024 * 1024:
        raise XmlObservationError("Project XML exceeds the bounded 25 MiB limit")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise XmlObservationError("DTD/entity declarations are forbidden in Project XML observations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise XmlObservationError(f"Project XML parse failed: {error}") from error
    if not root.tag.startswith("{"):
        raise XmlObservationError("Project XML has no namespace")
    namespace = root.tag[1:].split("}", 1)[0]
    return root, namespace


def parse_project_xml_observation(path: Path) -> dict[str, Any]:
    root, namespace = _safe_xml_root(path)
    q = lambda name: f"{{{namespace}}}{name}"  # noqa: E731
    text = lambda parent, name: (parent.findtext(q(name)) if parent is not None else None)  # noqa: E731
    tasks: list[dict[str, Any]] = []
    tasks_parent = root.find(q("Tasks"))
    if tasks_parent is not None:
        for task in tasks_parent.findall(q("Task")):
            links = []
            for link in task.findall(q("PredecessorLink")):
                links.append(
                    {
                        "predecessor_uid": text(link, "PredecessorUID"),
                        "type": text(link, "Type"),
                        "link_lag": text(link, "LinkLag"),
                        "lag_format": text(link, "LagFormat"),
                    }
                )
            tasks.append(
                {
                    "uid": text(task, "UID"),
                    "id": text(task, "ID"),
                    "name": text(task, "Name"),
                    "start": text(task, "Start"),
                    "finish": text(task, "Finish"),
                    "duration": text(task, "Duration"),
                    "manual": text(task, "Manual"),
                    "type": text(task, "Type"),
                    "effort_driven": text(task, "EffortDriven"),
                    "calendar_uid": text(task, "CalendarUID"),
                    "constraint_type": text(task, "ConstraintType"),
                    "constraint_date": text(task, "ConstraintDate"),
                    "actual_start": text(task, "ActualStart"),
                    "actual_finish": text(task, "ActualFinish"),
                    "actual_duration": text(task, "ActualDuration"),
                    "actual_work": text(task, "ActualWork"),
                    "percent_complete": text(task, "PercentComplete"),
                    "predecessor_links": links,
                }
            )
    calendars: list[dict[str, Any]] = []
    calendars_parent = root.find(q("Calendars"))
    if calendars_parent is not None:
        for calendar in calendars_parent.findall(q("Calendar")):
            weekdays: list[dict[str, Any]] = []
            weekday_parent = calendar.find(q("WeekDays"))
            if weekday_parent is not None:
                for weekday in weekday_parent.findall(q("WeekDay")):
                    working_times: list[dict[str, str | None]] = []
                    working_parent = weekday.find(q("WorkingTimes"))
                    if working_parent is not None:
                        for working in working_parent.findall(q("WorkingTime")):
                            working_times.append(
                                {"from_time": text(working, "FromTime"), "to_time": text(working, "ToTime")}
                            )
                    weekdays.append(
                        {
                            "day_type": text(weekday, "DayType"),
                            "day_working": text(weekday, "DayWorking"),
                            "working_times": working_times,
                        }
                    )
            calendars.append(
                {
                    "uid": text(calendar, "UID"),
                    "name": text(calendar, "Name"),
                    "is_base_calendar": text(calendar, "IsBaseCalendar"),
                    "base_calendar_uid": text(calendar, "BaseCalendarUID"),
                    "weekdays": weekdays,
                }
            )
    resources: list[dict[str, Any]] = []
    resources_parent = root.find(q("Resources"))
    if resources_parent is not None:
        for resource in resources_parent.findall(q("Resource")):
            resources.append(
                {
                    "uid": text(resource, "UID"),
                    "id": text(resource, "ID"),
                    "name": text(resource, "Name"),
                    "is_null": text(resource, "IsNull"),
                    "actual_work": text(resource, "ActualWork"),
                }
            )
    assignments: list[dict[str, Any]] = []
    assignments_parent = root.find(q("Assignments"))
    if assignments_parent is not None:
        for assignment in assignments_parent.findall(q("Assignment")):
            assignments.append(
                {
                    "uid": text(assignment, "UID"),
                    "task_uid": text(assignment, "TaskUID"),
                    "resource_uid": text(assignment, "ResourceUID"),
                    "percent_work_complete": text(
                        assignment, "PercentWorkComplete"
                    ),
                    "actual_start": text(assignment, "ActualStart"),
                    "actual_finish": text(assignment, "ActualFinish"),
                    "actual_work": text(assignment, "ActualWork"),
                }
            )
    return {
        "namespace": namespace,
        "save_version": text(root, "SaveVersion"),
        "project": {
            "start": text(root, "StartDate") or text(root, "Start"),
            "finish": text(root, "FinishDate") or text(root, "Finish"),
            "calendar_uid": text(root, "CalendarUID"),
            "status_date": text(root, "StatusDate"),
        },
        "tasks": tasks,
        "calendars": calendars,
        "resources": resources,
        "assignments": assignments,
    }


def validated_cal24x7_calendar(xml_observation: Mapping[str, Any]) -> dict[str, Any]:
    """Return the one complete Project 24 Hours base calendar or fail closed."""

    calendars = xml_observation.get("calendars")
    if not isinstance(calendars, list):
        raise XmlObservationError("Project XML calendars collection is missing")
    matches = [
        item
        for item in calendars
        if isinstance(item, Mapping) and item.get("name") == "24 Hours"
    ]
    if len(matches) != 1:
        raise XmlObservationError(
            f"Project XML must contain exactly one 24 Hours calendar; observed {len(matches)}"
        )
    calendar = dict(matches[0])
    if (
        not isinstance(calendar.get("uid"), str)
        or not calendar["uid"]
        or calendar.get("is_base_calendar") != "1"
        or calendar.get("base_calendar_uid") != "0"
    ):
        raise XmlObservationError(
            "24 Hours calendar base-calendar identity is incomplete"
        )
    project = xml_observation.get("project")
    if not isinstance(project, Mapping) or project.get("calendar_uid") != calendar["uid"]:
        raise XmlObservationError(
            "project does not select the unique 24 Hours calendar"
        )
    weekdays = calendar.get("weekdays")
    if not isinstance(weekdays, list) or len(weekdays) != 7:
        raise XmlObservationError(
            "24 Hours calendar must contain exactly seven weekdays"
        )
    by_day: dict[str, Mapping[str, Any]] = {}
    for weekday in weekdays:
        if not isinstance(weekday, Mapping):
            raise XmlObservationError("24 Hours weekday is malformed")
        day_type = weekday.get("day_type")
        if not isinstance(day_type, str) or day_type in by_day:
            raise XmlObservationError(
                "24 Hours weekday types are missing or duplicated"
            )
        by_day[day_type] = weekday
    if set(by_day) != {str(value) for value in range(1, 8)}:
        raise XmlObservationError(
            "24 Hours weekday types must be exactly 1 through 7"
        )
    expected_interval = [
        {"from_time": "00:00:00", "to_time": "00:00:00"}
    ]
    for day_type in sorted(by_day):
        weekday = by_day[day_type]
        if (
            weekday.get("day_working") != "1"
            or weekday.get("working_times") != expected_interval
        ):
            raise XmlObservationError(
                f"24 Hours weekday {day_type} is not one continuous midnight interval"
            )
    return calendar


def build_tracked_summary(
    *,
    run_id: str,
    environment: Mapping[str, Any],
    comparison: Mapping[str, Any],
    reopen_results: Sequence[Mapping[str, Any]],
    calendar_characterisation: Mapping[str, Any],
    raw_hashes: Sequence[Mapping[str, Any]],
    procedural_blinding: Mapping[str, Any],
    native_execution_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    product = environment.get("microsoft_project")
    executable = environment.get("project_executable")
    comparison_cases = comparison.get("cases")
    process_ids_by_case = (
        native_execution_evidence.get("process_ids_by_case")
        if isinstance(native_execution_evidence, Mapping)
        else None
    )
    process_evidence_complete = bool(
        isinstance(process_ids_by_case, Mapping)
        and set(process_ids_by_case) == set(CASE_IDS)
        and all(
            isinstance(process_ids_by_case[case_id], Sequence)
            and not isinstance(process_ids_by_case[case_id], (str, bytes))
            and process_ids_by_case[case_id]
            and all(
                isinstance(pid, int) and pid > 0
                for pid in process_ids_by_case[case_id]
            )
            for case_id in CASE_IDS
        )
    )
    actual_engine_ran = bool(
        isinstance(product, Mapping)
        and product.get("com_prog_id") == "MSProject.Application"
        and isinstance(product.get("version"), (str, int))
        and isinstance(executable, Mapping)
        and isinstance(executable.get("sha256"), str)
        and _HEX_RE.fullmatch(str(executable["sha256"]).lower())
        and isinstance(comparison_cases, list)
        and {item.get("case_id") for item in comparison_cases if isinstance(item, Mapping)}
        == set(CASE_IDS)
        and process_evidence_complete
    )
    limitations = [
        "Characterisation only; it does not satisfy manual_native_semantic_parity.",
        "The relationship cases are a partial subset and cannot establish full compatibility.",
        "CAL-24X7 observation does not automatically remove the Track C blocker.",
    ]
    if procedural_blinding.get(
        "clean_blind_classification_permitted"
    ) is False or "breach" in str(procedural_blinding.get("status", "")).lower():
        limitations.append(
            "Procedural non-access blinding was breached before execution; no clean blinding classification is permitted."
        )
    else:
        limitations.append(
            "Procedural blinding status is reported from the supplied run evidence and is not inferred as clean."
        )
    limitations.append(
        "Retained v0.1 case manifests record common prelaunch automation and source hashes, but the immutable v0.1 worker observations do not self-report those identities; v0.2 requires both bindings."
    )
    payload = {
        "schema_version": "headless-msproject-characterisation-summary-v0.1",
        "characterisation_label": TRACK_ID,
        "run_id": run_id,
        "execution_mechanism": "headless COM automation via MSProject.Application",
        "actual_microsoft_project_engine_ran": actual_engine_ran,
        "environment": dict(environment),
        "comparison": dict(comparison),
        "reopen_recalculate_characterisation": list(reopen_results),
        "cal_24x7_xml_characterisation": dict(calendar_characterisation),
        "raw_artifact_hashes": list(raw_hashes),
        "procedural_blinding": dict(procedural_blinding),
        "claim_boundary": {
            "manual_native_semantic_parity_track_executed": False,
            "saved_file_reopen_recalculate_stability_track_executed": False,
            "adapter_interchange_round_trip_track_executed": False,
            "track_c_preparation_blocked_unchanged": True,
            "full_microsoft_project_compatibility_claim": False,
            "adapter_claim": False,
            "mpp_binary_compatibility_claim": False,
            "optimizer_involved": False,
            "claim_eligible": False,
        },
        "limitations": limitations,
    }
    encoded = json.dumps(payload, sort_keys=True)
    if "executed_pass" in encoded:
        raise HeadlessCharacterisationError("tracked characterisation summary cannot emit executed_pass")
    return payload
