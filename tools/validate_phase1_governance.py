from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path("requirements/phase1-ci.lock")
LOCK_SHA256 = "74b5ba48ac5fb911b95357f405f7086e6f36abdf9b544b73cc587efa4b39220d"
PRIOR_V02_SUITE_HASH = "66e667afc94f4f32dad3cd098e933113645e6047669951e6cc39fde4ec4bef6c"
EXPECTED_DISTRIBUTIONS = {
    "attrs": "26.1.0",
    "jsonschema": "4.26.0",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.37.0",
    "rfc3339-validator": "0.1.4",
    "rpds-py": "2026.6.3",
    "setuptools": "80.9.0",
    "six": "1.17.0",
    "typing-extensions": "4.16.0",
}
MSPROJECT_PILOT_ID = "microsoft-project-relationship-v0.1"
MSPROJECT_PILOT_CASE_IDS = tuple(f"SEM-REL-{number:03d}" for number in range(1, 13))
MSPROJECT_PILOT_INPUT_IDENTITY_DOMAIN = (
    "microsoft-project-relationship-pilot-input-identity-v0.2"
)
ACCEPTANCE_WORKFLOWS = {
    "validate-phase0.yml": "phase0-validation",
    "validate-phase1.yml": "phase1-validation",
}
REVIEWED_ACTION_PINS = {
    "actions/checkout": {
        "sha": "11d5960a326750d5838078e36cf38b85af677262",
        "release_tag": "v4.4.0",
    },
    "actions/setup-python": {
        "sha": "a26af69be951a213d495a4c3e4e4022e16d87065",
        "release_tag": "v5.6.0",
    },
}
_FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
_ACTION_REFERENCE = re.compile(
    r"^\s*-\s+uses:\s+([^@\s#]+)@([^\s#]+)(?:\s+#\s*(\S+)\s*)?$"
)
_ACTION_USES_KEY = re.compile(
    r'''(?:^\s*(?:-\s*)?|[,{]\s*)(?:uses|'uses'|"uses")\s*:'''
)
_ACTION_SHAPED_REFERENCE = re.compile(
    r'''(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[^\s#,'"}\]]+'''
)
_EXPECTED_WORKFLOW_TRIGGER_LINES = [
    "on:",
    "  push:",
    "    branches:",
    '      - "**"',
    "  pull_request:",
    "    branches:",
    "      - main",
]
EXPECTED_GOVERNANCE = {
    "schema_version": "repository-governance-v0.1",
    "target": "default_branch",
    "default_branch": "main",
    "live_ruleset_required": True,
    "required_pull_request": True,
    "required_approvals": 0,
    "dismiss_stale_reviews": True,
    "require_conversation_resolution": True,
    "require_branch_up_to_date": True,
    "required_status_checks": ["phase0-validation", "phase1-validation"],
    "allow_force_pushes": False,
    "allow_deletions": False,
    "administrator_bypass": False,
    "notes": (
        "This tracked policy does not replace the live GitHub ruleset. "
        "The live setting must be independently verified."
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _definition_validator(schema: dict[str, Any], definition: str) -> Draft202012Validator:
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{definition}",
        "$defs": schema["$defs"],
    }
    Draft202012Validator.check_schema(wrapper)
    return Draft202012Validator(wrapper, format_checker=FormatChecker())


def _native_schema_self_probe_errors(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    run_validator = _definition_validator(schema, "nativeRunEvidenceRecord")
    manifest_validator = _definition_validator(schema, "redactedEvidenceManifest")
    digest = "0" * 64
    p6_preregistration_hash = "953b06227fcb636be14b1b7602497054653550424259c31f227e76245605fbc0"
    p6_profile_hash = "a2d665dd30f24e715411097cea81526e67f44b0b258d333b76c7e6bf934e4511"
    valid_run = {
        "schema_version": "native-run-evidence-v0.1",
        "run_id": "schema-probe",
        "preregistration_id": "p6-semantic-microcases-v0.1",
        "preregistration_raw_sha256": p6_preregistration_hash,
        "comparison_profile_id": "p6-semantic-comparison-profile-v0.1",
        "comparison_profile_raw_sha256": p6_profile_hash,
        "native_system": "p6",
        "case_id": "SEM-REL-001",
        "execution_track_id": "adapter_interchange_round_trip",
        "status": "executed_pass",
        "executed_at": "2026-08-24T00:00:00Z",
        "operator_id": "operator",
        "independent_reviewer_id": "reviewer",
        "environment_capture_sha256": digest,
        "fixture_raw_sha256": digest,
        "case_realization_manifest_sha256": digest,
        "native_artifact_hashes_by_stage": {
            "native_pre_export_file_sha256": digest,
            "p6_xml_export_sha256": digest,
            "canonical_reimport_sha256": digest,
            "controlled_reexport_sha256": digest,
            "native_reopened_recalculated_file_sha256": digest,
            "final_normalized_native_output_sha256": digest,
        },
        "normalized_output_sha256": digest,
        "field_difference_manifest_sha256": digest,
        "manual_action_log_sha256": digest,
        "evidence_bundle_sha256": digest,
        "failure_or_inconclusive_reason": None,
        "review_disposition": "accepted",
    }
    artifact_roles = [
        "preregistration",
        "comparison_profile",
        "case_realization_manifest",
        "environment_capture",
        "native_input",
        "native_stage_output",
        "normalized_output",
        "field_difference_manifest",
        "manual_action_log",
        "independent_review",
    ]
    artifact_index = [
        {
            "artifact_role": role,
            "relative_or_controlled_external_location": f"artifacts/{role}",
            "sha256": digest,
            "byte_size": 0,
            "media_type": "application/octet-stream",
            "contains_restricted_data": False,
            "retention_owner": "evidence-owner",
        }
        for role in artifact_roles
    ]
    valid_manifest = {
        "schema_version": "native-redacted-evidence-manifest-v0.1",
        "run_id": "schema-probe",
        "preregistration_id": "p6-semantic-microcases-v0.1",
        "preregistration_raw_sha256": p6_preregistration_hash,
        "comparison_profile_id": "p6-semantic-comparison-profile-v0.1",
        "comparison_profile_raw_sha256": p6_profile_hash,
        "native_system": "p6",
        "product_edition_version_build": {
            "product_name": "Primavera P6",
            "edition": "probe",
            "version": "probe",
            "build": "probe",
        },
        "execution_track_id": "adapter_interchange_round_trip",
        "case_outcomes": [
            {
                "case_id": "SEM-REL-001",
                "execution_track_id": "adapter_interchange_round_trip",
                "status": "executed_pass",
                "run_record_sha256": digest,
            }
        ],
        "artifact_index": artifact_index,
        "environment_capture_sha256": digest,
        "difference_manifest_sha256": digest,
        "review_disposition": "accepted",
        "created_at": "2026-08-24T00:00:00Z",
    }
    if not run_validator.is_valid(valid_run):
        errors.append("native evidence schema rejects its conforming run-record self-probe")
    if not manifest_validator.is_valid(valid_manifest):
        errors.append("native evidence schema rejects its conforming manifest self-probe")

    cross_product_run = copy.deepcopy(valid_run)
    cross_product_run.update(
        {
            "preregistration_id": "microsoft-project-semantic-microcases-v0.1",
            "preregistration_raw_sha256": (
                "69594ba766cea5f204bc41f99f49af28a65b6f543919dad2bee702a9f6e0b647"
            ),
            "comparison_profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
            "comparison_profile_raw_sha256": (
                "8ab9c47395897e13f5b6cf36773757f4bd5a273e997b81de78585d76e872a469"
            ),
        }
    )
    if run_validator.is_valid(cross_product_run):
        errors.append("native evidence schema accepts a cross-product run record")

    missing_stage_run = copy.deepcopy(valid_run)
    del missing_stage_run["native_artifact_hashes_by_stage"]["p6_xml_export_sha256"]
    if run_validator.is_valid(missing_stage_run):
        errors.append("native evidence schema accepts an incomplete P6 adapter stage-hash set")

    cross_product_manifest = copy.deepcopy(valid_manifest)
    cross_product_manifest.update(
        {
            "preregistration_id": "microsoft-project-semantic-microcases-v0.1",
            "preregistration_raw_sha256": (
                "69594ba766cea5f204bc41f99f49af28a65b6f543919dad2bee702a9f6e0b647"
            ),
            "comparison_profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
            "comparison_profile_raw_sha256": (
                "8ab9c47395897e13f5b6cf36773757f4bd5a273e997b81de78585d76e872a469"
            ),
            "product_edition_version_build": {
                "product_name": "Microsoft Project",
                "edition": "probe",
                "version": "probe",
                "build": "probe",
            },
        }
    )
    if manifest_validator.is_valid(cross_product_manifest):
        errors.append("native evidence schema accepts a cross-product redacted manifest")

    incomplete_manifest = copy.deepcopy(valid_manifest)
    incomplete_manifest["artifact_index"] = artifact_index[:1]
    if manifest_validator.is_valid(incomplete_manifest):
        errors.append("native evidence schema accepts an incomplete manifest artifact-role set")
    return errors


def _committed_native_manifest_errors(
    root: Path,
    schema: dict[str, Any],
    specifications: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    manifest_validator = _definition_validator(schema, "redactedEvidenceManifest")
    evidence_index = root / "native-validation" / "evidence-index"
    if not evidence_index.is_dir():
        return errors
    by_system = {system: item for system, item in specifications.items()}
    for path in sorted(evidence_index.rglob("manifest.json")):
        relative = path.relative_to(root).as_posix()
        try:
            manifest = _load_json(path)
        except Exception as exc:
            errors.append(f"{relative}: committed native evidence manifest is invalid JSON: {exc}")
            continue
        for problem in sorted(manifest_validator.iter_errors(manifest), key=lambda item: list(item.path)):
            location = "/".join(str(part) for part in problem.path) or "<root>"
            errors.append(f"{relative} {location}: {problem.message}")
        system = manifest.get("native_system")
        expected = by_system.get(system)
        if expected is None:
            continue
        run_id = manifest.get("run_id")
        expected_relative = (
            "native-validation/evidence-index/"
            f"{expected['plan_id']}/{run_id}/manifest.json"
        )
        if relative != expected_relative:
            errors.append(f"{relative}: manifest path does not match its product, plan and run ID")
        plan_path = root / "native-validation" / "preregistrations" / expected["plan_file"]
        profile_path = root / "native-validation" / "profiles" / expected["profile_file"]
        if not plan_path.is_file() or not profile_path.is_file():
            errors.append(f"{relative}: frozen plan/profile file is unavailable")
            continue
        if (
            manifest.get("preregistration_raw_sha256") != _sha256(plan_path)
            or manifest.get("comparison_profile_raw_sha256") != _sha256(profile_path)
        ):
            errors.append(f"{relative}: manifest does not bind the current frozen plan/profile bytes")
        profile = _load_json(profile_path)
        execution_case_ids = set(profile["scope"]["execution_case_ids"])
        outcomes = manifest.get("case_outcomes", [])
        outcome_keys = [
            (item.get("case_id"), item.get("execution_track_id"))
            for item in outcomes
            if isinstance(item, dict)
        ]
        if len(outcome_keys) != len(set(outcome_keys)):
            errors.append(f"{relative}: duplicate case/track outcomes are forbidden")
        if any(case_id not in execution_case_ids for case_id, _ in outcome_keys):
            errors.append(f"{relative}: manifest contains a case outside the frozen execution subset")
    return errors


def validate_dependency_lock(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    lock = root / LOCK_PATH
    if not lock.is_file():
        return [f"dependency lock is missing: {LOCK_PATH.as_posix()}"]
    if _sha256(lock) != LOCK_SHA256:
        errors.append("dependency lock SHA-256 does not match deterministic-v0.3")
    declarations = {
        name.lower().replace("_", "-"): version
        for name, version in re.findall(
            r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\s*\\$",
            lock.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    }
    if declarations != EXPECTED_DISTRIBUTIONS:
        errors.append("dependency lock does not declare the complete pinned distribution set")
    text = lock.read_text(encoding="utf-8")
    for name, version in EXPECTED_DISTRIBUTIONS.items():
        declaration = f"{name}=={version}"
        if declaration not in text or "--hash=sha256:" not in text[text.index(declaration) :]:
            errors.append(f"dependency lock lacks a hashed declaration for {declaration}")
    return errors


def validate_native_preregistrations(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    preregistration_dir = root / "native-validation" / "preregistrations"
    profile_dir = root / "native-validation" / "profiles"
    schema_path = root / "schemas" / "native-validation-preregistration.schema.json"
    specifications = {
        "p6": {
            "plan_file": "p6-semantic-microcases-v0.1.json",
            "plan_id": "p6-semantic-microcases-v0.1",
            "plan_hash": "953b06227fcb636be14b1b7602497054653550424259c31f227e76245605fbc0",
            "profile_file": "p6-semantic-comparison-profile-v0.1.json",
            "profile_id": "p6-semantic-comparison-profile-v0.1",
            "profile_hash": "a2d665dd30f24e715411097cea81526e67f44b0b258d333b76c7e6bf934e4511",
            "characterization": ["SEM-STA-045"],
            "evidence_root": "native-files/p6/p6-semantic-microcases-v0.1",
        },
        "microsoft_project": {
            "plan_file": "microsoft-project-semantic-microcases-v0.1.json",
            "plan_id": "microsoft-project-semantic-microcases-v0.1",
            "plan_hash": "69594ba766cea5f204bc41f99f49af28a65b6f543919dad2bee702a9f6e0b647",
            "profile_file": "microsoft-project-semantic-comparison-profile-v0.1.json",
            "profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
            "profile_hash": "8ab9c47395897e13f5b6cf36773757f4bd5a273e997b81de78585d76e872a469",
            "characterization": ["SEM-STA-043", "SEM-STA-044", "SEM-STA-045"],
            "evidence_root": "native-files/microsoft-project/microsoft-project-semantic-microcases-v0.1",
        },
    }
    expected_plan_files = {item["plan_file"] for item in specifications.values()}
    expected_profile_files = {item["profile_file"] for item in specifications.values()}
    discovered_plans = (
        {path.name for path in preregistration_dir.glob("*.json")}
        if preregistration_dir.is_dir()
        else set()
    )
    discovered_profiles = (
        {path.name for path in profile_dir.glob("*.json")}
        if profile_dir.is_dir()
        else set()
    )
    if discovered_plans != expected_plan_files:
        errors.append("native preregistration file set is not the exact separate P6/MS Project pair")
    if discovered_profiles != expected_profile_files:
        errors.append("native comparison-profile file set is not the exact separate P6/MS Project pair")
    if not schema_path.is_file():
        return errors + ["native validation closed schema is missing"]
    try:
        schema = _load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    except Exception as exc:
        return errors + [f"native validation schema is invalid: {exc}"]
    errors.extend(_native_schema_self_probe_errors(schema))

    catalogue_path = root / "benchmarks" / "semantic" / "catalogue.csv"
    with catalogue_path.open("r", encoding="utf-8", newline="") as stream:
        ordered_case_ids = [row["case_id"] for row in csv.DictReader(stream)]
    execution_case_ids = ordered_case_ids[:48]
    excluded_case_ids = ordered_case_ids[48:]
    case_dir = root / "benchmarks" / "semantic" / "cases"
    fixture_lines = []
    for case_id in sorted(execution_case_ids):
        fixture_path = case_dir / f"{case_id.lower()}.json"
        fixture_lines.append(f"{case_id} {_sha256(fixture_path)}\n")
    fixture_set_hash = hashlib.sha256("".join(fixture_lines).encode("utf-8")).hexdigest()

    evidence_roots: set[str] = set()
    for system, expected in specifications.items():
        plan_path = preregistration_dir / str(expected["plan_file"])
        profile_path = profile_dir / str(expected["profile_file"])
        if not plan_path.is_file() or not profile_path.is_file():
            continue
        try:
            plan = _load_json(plan_path)
            profile = _load_json(profile_path)
        except Exception as exc:
            errors.append(f"{system}: native validation JSON is invalid: {exc}")
            continue
        for label, document in (("preregistration", plan), ("comparison profile", profile)):
            for problem in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
                location = "/".join(str(part) for part in problem.path) or "<root>"
                errors.append(f"{system} {label} {location}: {problem.message}")

        if (
            plan.get("document_type") != "native_validation_preregistration"
            or plan.get("preregistration_id") != expected["plan_id"]
            or plan.get("native_system") != system
            or plan.get("status") != "preregistered_not_executed"
            or _sha256(plan_path) != expected["plan_hash"]
        ):
            errors.append(f"{system}: preregistration identity/status is not frozen")
        research = plan.get("research_state_at_preregistration", {})
        if (
            research.get("reference_execution_profile") != "deterministic-v0.2"
            or research.get("reference_suite_hash") != PRIOR_V02_SUITE_HASH
            or research.get("reference_execution_results_existed") is not True
            or research.get("native_results_existed") is not False
            or research.get("native_round_trip_result_existed") is not False
        ):
            errors.append(f"{system}: historical reference/native result state is not preserved")
        binding = plan.get("profile_binding", {})
        if (
            binding.get("profile_id") != expected["profile_id"]
            or binding.get("path")
            != f"native-validation/profiles/{expected['profile_file']}"
            or binding.get("raw_file_sha256") != expected["profile_hash"]
            or _sha256(profile_path) != expected["profile_hash"]
        ):
            errors.append(f"{system}: preregistration does not bind the exact frozen profile bytes")
        evidence_root = plan.get("evidence_manifest_contract", {}).get("raw_evidence_root")
        if evidence_root != expected["evidence_root"]:
            errors.append(f"{system}: product-specific raw evidence root is not frozen")
        evidence_roots.add(str(evidence_root))

        if (
            profile.get("document_type") != "native_semantic_comparison_profile"
            or profile.get("profile_id") != expected["profile_id"]
            or profile.get("native_system") != system
            or profile.get("status") != "frozen_preregistered_not_executed"
        ):
            errors.append(f"{system}: comparison profile identity/status is not frozen")
        corpus = profile.get("corpus_binding", {})
        if (
            corpus.get("catalogue_sha256") != _sha256(catalogue_path)
            or corpus.get("case_file_set_sha256") != fixture_set_hash
        ):
            errors.append(f"{system}: comparison profile corpus hashes do not match frozen bytes")
        scope = profile.get("scope", {})
        characterization = [
            item.get("case_id")
            for item in scope.get("characterization_only_cases", [])
            if isinstance(item, dict)
        ]
        expected_characterization = list(expected["characterization"])
        expected_claim_cases = [
            case_id for case_id in execution_case_ids if case_id not in expected_characterization
        ]
        if (
            scope.get("execution_case_ids") != execution_case_ids
            or scope.get("claim_eligible_case_ids") != expected_claim_cases
            or characterization != expected_characterization
            or scope.get("excluded_case_ids") != excluded_case_ids
        ):
            errors.append(f"{system}: execution/claim/characterization case partition is not exact")
        coordinate = profile.get("coordinate_contract", {})
        if any(
            coordinate.get(field) != 0
            for field in (
                "timestamp_tolerance_seconds",
                "duration_tolerance_seconds",
                "float_tolerance_seconds",
            )
        ) or coordinate.get("rounding_policy") != "forbidden":
            errors.append(f"{system}: exact coordinate/tolerance contract is not frozen")
        tracks = profile.get("execution_tracks", [])
        track_ids = [item.get("track_id") for item in tracks if isinstance(item, dict)]
        if track_ids != [
            "manual_native_semantic_parity",
            "saved_file_reopen_recalculate_stability",
            "adapter_interchange_round_trip",
        ]:
            errors.append(f"{system}: three independent execution tracks are not exact")
        elif (
            tracks[0].get("can_satisfy_native_semantic_gate") is not True
            or tracks[1].get("can_satisfy_reopen_stability_gate") is not True
            or tracks[2].get("can_satisfy_adapter_interchange_gate") is not True
            or tracks[2].get("manual_transcription_allowed") is not False
        ):
            errors.append(f"{system}: evidence tracks can substitute for the wrong gate")
        plan_tracks = plan.get("execution_track_separation", [])
        if [item.get("track_id") for item in plan_tracks if isinstance(item, dict)] != track_ids:
            errors.append(f"{system}: plan/profile evidence-track order differs")
        if plan.get("status_and_decision_rules", {}).get("full_compatibility_status_does_not_exist") is not True:
            errors.append(f"{system}: general product compatibility remains insufficiently bounded")

    if len(evidence_roots) != 2:
        errors.append("P6 and Microsoft Project preregistrations must use distinct evidence roots")
    errors.extend(_committed_native_manifest_errors(root, schema, specifications))
    return errors


def _workflow_trigger_errors(filename: str, text: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index("on:")
    except ValueError:
        return [f"{filename}: workflow trigger declaration is missing"]
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line and not line.startswith((" ", "\t", "#")):
            break
        end += 1
    trigger_lines = [line for line in lines[start:end] if line and not line.lstrip().startswith("#")]
    if trigger_lines != _EXPECTED_WORKFLOW_TRIGGER_LINES:
        return [
            f"{filename}: push must cover every feature branch and pull_request must target only main"
        ]
    return []


def _workflow_action_pin_errors(filename: str, text: str) -> list[str]:
    errors: list[str] = []
    seen = {action: 0 for action in REVIEWED_ACTION_PINS}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        if (
            _ACTION_USES_KEY.search(line) is None
            and _ACTION_SHAPED_REFERENCE.search(line) is None
        ):
            continue
        match = _ACTION_REFERENCE.fullmatch(line)
        if match is None:
            errors.append(f"{filename}:{line_number}: action reference is not a pinned uses declaration")
            continue
        action, reference, comment = match.groups()
        reviewed = REVIEWED_ACTION_PINS.get(action)
        if reviewed is None:
            errors.append(f"{filename}:{line_number}: unreviewed or non-official action {action} is forbidden")
            continue
        seen[action] += 1
        if _FULL_COMMIT_SHA.fullmatch(reference) is None:
            errors.append(
                f"{filename}:{line_number}: {action} must use an immutable full commit SHA"
            )
        elif reference != reviewed["sha"]:
            errors.append(
                f"{filename}:{line_number}: {action} does not use the reviewed commit SHA"
            )
        if comment != reviewed["release_tag"]:
            errors.append(
                f"{filename}:{line_number}: {action} must retain reviewed release tag comment "
                f"{reviewed['release_tag']}"
            )
    for action, count in seen.items():
        if count != 1:
            errors.append(f"{filename}: {action} must appear exactly once at its reviewed pin")
    return errors


def validate_workflow_governance(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    install_lock = (
        "python -m pip install --require-hashes --only-binary=:all: "
        "-r requirements/phase1-ci.lock"
    )
    install_project = "python -m pip install --no-deps --no-build-isolation -e ."
    for filename, check_name in ACCEPTANCE_WORKFLOWS.items():
        path = root / ".github" / "workflows" / filename
        if not path.is_file():
            errors.append(f"workflow is missing: {filename}")
            continue
        text = path.read_text(encoding="utf-8")
        if f"  {check_name}:" not in text or f"name: {check_name}" not in text:
            errors.append(f"{filename}: stable unique check name {check_name} is missing")
        errors.extend(_workflow_trigger_errors(filename, text))
        errors.extend(_workflow_action_pin_errors(filename, text))
        if "phase0-protocol-freeze" in text or "phase1-reference-cpm-kernel" in text:
            errors.append(f"{filename}: obsolete branch trigger remains")
        if install_lock not in text or install_project not in text:
            errors.append(f"{filename}: hash-locked install sequence is incomplete")
        if "cache-dependency-path: requirements/phase1-ci.lock" not in text:
            errors.append(f"{filename}: setup-python cache is not bound to the lock")
    governance_path = root / ".github" / "repository-governance.json"
    if not governance_path.is_file() or _load_json(governance_path) != EXPECTED_GOVERNANCE:
        errors.append("tracked repository governance policy does not match the required main ruleset")
    return errors


def recompute_msproject_pilot_input_identity(
    root: Path, kit: Path
) -> tuple[dict[str, Any], str]:
    """Recompute the pilot input projection from live raw repository bytes."""

    preregistration_path = Path(
        "native-validation/preregistrations/"
        "microsoft-project-semantic-microcases-v0.1.json"
    )
    comparison_profile_path = Path(
        "native-validation/profiles/"
        "microsoft-project-semantic-comparison-profile-v0.1.json"
    )

    def raw_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    projection = {
        "hash_domain": MSPROJECT_PILOT_INPUT_IDENTITY_DOMAIN,
        "pilot_id": MSPROJECT_PILOT_ID,
        "ordered_case_ids": list(MSPROJECT_PILOT_CASE_IDS),
        "preregistration": {
            "relative_path": preregistration_path.as_posix(),
            "raw_sha256": raw_sha256(root / preregistration_path),
        },
        "comparison_profile": {
            "relative_path": comparison_profile_path.as_posix(),
            "raw_sha256": raw_sha256(root / comparison_profile_path),
        },
        "source_only_case_projections": [
            {
                "case_id": case_id,
                "relative_path": (
                    "native-validation/pilot-kits/"
                    f"{MSPROJECT_PILOT_ID}/source-only-case-projections/"
                    f"{case_id}.json"
                ),
                "raw_sha256": raw_sha256(
                    kit / "source-only-case-projections" / f"{case_id}.json"
                ),
            }
            for case_id in MSPROJECT_PILOT_CASE_IDS
        ],
        "mapping_source_register": {
            "relative_path": "mapping-source-register.json",
            "raw_sha256": raw_sha256(kit / "mapping-source-register.json"),
        },
    }
    return projection, hashlib.sha256(canonical_bytes(projection)).hexdigest()


def validate_msproject_pilot_oracle_blinding(
    root: Path, kit: Path
) -> list[str]:
    """Require operator packets to bind only source projections, never oracles."""

    errors: list[str] = []
    try:
        index = _load_json(kit / "pilot-index.json")
    except Exception as exc:
        return [f"Microsoft Project pilot oracle blinding cannot load index: {exc}"]
    case_entries = {
        item.get("case_id"): item
        for item in index.get("cases", [])
        if isinstance(item, dict)
    }
    visible_payloads = [
        path
        for path in sorted(kit.rglob("*"))
        if path.is_file() and "sealed-expected-normalized" not in path.parts
    ]
    visible_bytes = b"\n".join(path.read_bytes() for path in visible_payloads)
    oracle_keys = {
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

    def all_keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                key for child in value.values() for key in all_keys(child)
            }
        if isinstance(value, list):
            return {key for child in value for key in all_keys(child)}
        return set()

    for case_id in MSPROJECT_PILOT_CASE_IDS:
        fixture_relative = f"benchmarks/semantic/cases/{case_id.lower()}.json"
        fixture_hash = _sha256(root / fixture_relative)
        if fixture_relative.encode("utf-8") in visible_bytes:
            errors.append(
                f"{case_id}: operator-visible pilot bytes expose the full fixture path"
            )
        if fixture_hash.encode("ascii") in visible_bytes:
            errors.append(
                f"{case_id}: operator-visible pilot bytes expose the full fixture hash"
            )

        projection_relative = f"source-only-case-projections/{case_id}.json"
        projection_path = kit / projection_relative
        try:
            projection = _load_json(projection_path)
            projection_hash = _sha256(projection_path)
        except Exception as exc:
            errors.append(f"{case_id}: source-only projection is invalid: {exc}")
            continue
        if not oracle_keys.isdisjoint(all_keys(projection)):
            errors.append(f"{case_id}: source-only projection contains oracle fields")
        contract = projection.get("projection_contract", {})
        if (
            contract.get("construction_inputs_only") is not True
            or contract.get("oracle_content_included") is not False
            or contract.get("full_fixture_binding_included") is not False
        ):
            errors.append(f"{case_id}: source-only projection contract is not blinded")

        case_entry = case_entries.get(case_id, {})
        if any(
            key in case_entry for key in ("fixture", "fixture_binding", "source_fixture")
        ):
            errors.append(f"{case_id}: pilot index retains a full-fixture binding alias")
        binding = case_entry.get("source_only_case_projection", {})
        expected_repository_path = (
            "native-validation/pilot-kits/"
            f"{MSPROJECT_PILOT_ID}/{projection_relative}"
        )
        if (
            binding.get("binding_role") != "source_only_case_projection"
            or binding.get("relative_path") != expected_repository_path
            or binding.get("path") != expected_repository_path
            or binding.get("raw_sha256") != projection_hash
            or binding.get("oracle_content_included") is not False
        ):
            errors.append(f"{case_id}: pilot index source-only binding is inconsistent")

        sealed_path = kit / "sealed-expected-normalized" / f"{case_id}.json"
        try:
            sealed = _load_json(sealed_path)
            full_binding = sealed["source_bindings"]["fixture"]
        except Exception as exc:
            errors.append(f"{case_id}: sealed full-fixture binding is missing: {exc}")
            continue
        if (
            full_binding.get("case_id") != case_id
            or full_binding.get("path") != fixture_relative
            or full_binding.get("relative_path") != fixture_relative
            or full_binding.get("raw_sha256") != fixture_hash
            or sealed.get("seal_control", {}).get(
                "full_oracle_fixture_binding_is_sealed"
            )
            is not True
        ):
            errors.append(f"{case_id}: sealed full-fixture binding is inconsistent")
    return errors


def validate_msproject_relationship_pilot(root: Path = ROOT) -> list[str]:
    """Validate the tracked preparation kit without treating it as native evidence."""

    errors: list[str] = []
    kit = root / "native-validation" / "pilot-kits" / MSPROJECT_PILOT_ID
    if not kit.is_dir():
        return ["Microsoft Project relationship pilot kit is missing"]

    try:
        from deterministic_scheduling_core.native.msproject.pilot import verify_pilot

        summary = verify_pilot(kit, repository_root=root)
    except Exception as exc:
        return [f"Microsoft Project relationship pilot regeneration failed: {exc}"]
    if summary.get("status") != "prepared_not_executed":
        errors.append("Microsoft Project relationship pilot status is not prepared_not_executed")
    if summary.get("case_ids") != list(MSPROJECT_PILOT_CASE_IDS):
        errors.append("Microsoft Project relationship pilot case identity/order changed")
    if summary.get("adapter_preparation_status") != "preparation_blocked":
        errors.append("Microsoft Project adapter preparation is not fail-closed")
    if summary.get("full_45_case_gate_satisfied") is not False:
        errors.append("partial Microsoft Project pilot incorrectly satisfies the 45-case gate")

    index_path = kit / "pilot-index.json"
    try:
        index = _load_json(index_path)
    except Exception as exc:
        errors.append(f"Microsoft Project pilot index is invalid JSON: {exc}")
        index = {}
    try:
        input_projection, input_digest = recompute_msproject_pilot_input_identity(
            root, kit
        )
    except Exception as exc:
        errors.append(f"Microsoft Project pilot input identity cannot be recomputed: {exc}")
        input_projection, input_digest = {}, ""
    input_identity = index.get("pilot_input_identity", {}) if isinstance(index, dict) else {}
    if input_identity != {
        "hash_algorithm": "sha256",
        "canonical_serialization": "dsc-canonical-json-v1",
        "projection": input_projection,
        "sha256": input_digest,
    }:
        errors.append(
            "Microsoft Project pilot input identity does not match live canonical inputs"
        )
    boundary = index.get("claim_boundary", {}) if isinstance(index, dict) else {}
    for field in (
        "native_execution_performed",
        "native_semantic_claim",
        "adapter_execution_performed",
        "adapter_interchange_claim",
        "full_microsoft_project_compatibility_claim",
        "optimizer_benchmark_performed",
        "optimizer_superiority_claim",
        "full_45_case_gate_satisfied",
    ):
        if boundary.get(field) is not False:
            errors.append(f"Microsoft Project pilot claim boundary does not keep {field} false")

    tracked_payloads = sorted(path for path in kit.rglob("*") if path.is_file())
    if len(tracked_payloads) != 95:
        errors.append(
            f"Microsoft Project pilot must contain exactly 95 prepared files, found {len(tracked_payloads)}"
        )
    forbidden_suffixes = {".mpp", ".mpx", ".xml"}
    forbidden = [
        path.relative_to(root).as_posix()
        for path in tracked_payloads
        if path.suffix.lower() in forbidden_suffixes
    ]
    if forbidden:
        errors.append("prepared pilot contains forbidden native/adapter payloads: " + ", ".join(forbidden))
    for path in tracked_payloads:
        if b'"executed_pass"' in path.read_bytes():
            errors.append(
                f"{path.relative_to(root).as_posix()}: preparation must not contain executed_pass"
            )
    errors.extend(validate_msproject_pilot_oracle_blinding(root, kit))

    register_path = root / "registers" / "experiment-register.csv"
    try:
        with register_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        errors.append(f"experiment register cannot be read: {exc}")
        rows = []
    pilot_rows = [row for row in rows if row.get("experiment_id") == MSPROJECT_PILOT_ID]
    if len(pilot_rows) != 1:
        errors.append("experiment register must contain exactly one Microsoft Project pilot row")
    else:
        row = pilot_rows[0]
        if row.get("execution_status") != "prepared_not_executed":
            errors.append("experiment register incorrectly records a native execution status")
        if row.get("input_hash") != input_digest:
            errors.append(
                "experiment register pilot input identity digest does not match live inputs"
            )
        if row.get("output_hash"):
            errors.append("prepared Microsoft Project pilot must not record a native output hash")
        if row.get("evidence_path") != (
            "native-validation/pilot-kits/microsoft-project-relationship-v0.1"
        ):
            errors.append("experiment register pilot evidence path is incorrect")
    return errors


def validate_metadata(root: Path = ROOT) -> list[str]:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    errors: list[str] = []
    if "Added 57 Phase 1 tests; the combined suite contains 124 tests" not in changelog:
        errors.append("CHANGELOG does not preserve the exact 57 Phase 1 / 124 combined count")
    harness = (root / "src" / "deterministic_scheduling_core" / "execution" / "harness.py").read_text(
        encoding="utf-8"
    )
    if '"suite_hash"' in harness:
        errors.append("ambiguous suite_hash remains in the Phase 1 harness")
    return errors


def collect_errors(root: Path = ROOT) -> list[str]:
    return (
        validate_dependency_lock(root)
        + validate_native_preregistrations(root)
        + validate_workflow_governance(root)
        + validate_msproject_relationship_pilot(root)
        + validate_metadata(root)
    )


def main() -> int:
    errors = collect_errors(ROOT)
    if errors:
        print("PHASE 1 GOVERNANCE VALIDATION: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PHASE 1 GOVERNANCE VALIDATION: PASS")
    print("- complete hash-locked dependency closure verified")
    print("- P6 and Microsoft Project preregistrations remain separate and unexecuted")
    print("- feature-branch push/main PR workflow policy and immutable action pins verified")
    print("- deterministic 12-case Microsoft Project pilot remains prepared-only and adapter-blocked")
    print("- exact Phase 1 test metadata and named hash domains verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
