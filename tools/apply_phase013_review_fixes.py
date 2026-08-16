from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def write(rel: str, value) -> None:
    (ROOT / rel).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def replace_objective_vectors(node, ref: str) -> None:
    if isinstance(node, dict):
        for key in list(node):
            if key in {"objective_vector", "selected_objective_vector", "result_objective_vector"} and isinstance(node[key], dict):
                node[key] = {"$ref": ref}
            else:
                replace_objective_vectors(node[key], ref)
    elif isinstance(node, list):
        for item in node:
            replace_objective_vectors(item, ref)


# Canonical schedule schema.
canon = load("schemas/canonical-schedule.schema.json")
defs = canon.setdefault("$defs", {})
activity = defs["activity"]
activity.setdefault("allOf", [])
activity["allOf"] = [x for x in activity["allOf"] if x.get("$comment") != "phase013-in-progress"]
activity["allOf"].append({
    "$comment": "phase013-in-progress",
    "if": {
        "required": ["actual_start", "actual_finish"],
        "properties": {
            "actual_start": {"not": {"type": "null"}},
            "actual_finish": {"type": "null"},
        },
    },
    "then": {
        "required": ["remaining_duration"],
        "properties": {"remaining_duration": {"type": "integer", "minimum": 0}},
    },
})

frozen_name = next((x for x in ("frozenState", "frozen_state") if x in defs), None)
if frozen_name:
    frozen = defs[frozen_name]
    fp = frozen.setdefault("properties", {})
    flag = next((x for x in ("is_frozen", "frozen") if x in fp), "is_frozen")
    start = next((x for x in ("fixed_start", "frozen_start", "start") if x in fp), "fixed_start")
    finish = next((x for x in ("fixed_finish", "frozen_finish", "finish") if x in fp), "fixed_finish")
    fp.setdefault(flag, {"type": "boolean"})
    fp.setdefault(start, {"type": ["integer", "null"]})
    fp.setdefault(finish, {"type": ["integer", "null"]})
    frozen.setdefault("allOf", [])
    frozen["allOf"] = [x for x in frozen["allOf"] if x.get("$comment") != "phase013-frozen"]
    frozen["allOf"].append({
        "$comment": "phase013-frozen",
        "if": {"required": [flag], "properties": {flag: {"const": True}}},
        "then": {
            "required": [start, finish],
            "properties": {start: {"type": "integer"}, finish: {"type": "integer"}},
        },
    })

state_name = next((x for x in ("scheduleState", "schedule_state") if x in defs), None)
if state_name:
    state = defs[state_name]
    state.setdefault("properties", {})["state_type"] = {
        "enum": ["baseline", "approved_forecast", "proposed_scenario"]
    }
    required = state.setdefault("required", [])
    if "state_type" not in required:
        required.insert(0, "state_type")
    for slot in ("baseline", "approved_forecast", "proposed_scenario"):
        if slot in canon.get("properties", {}):
            canon["properties"][slot] = {
                "anyOf": [
                    {"type": "null"},
                    {
                        "allOf": [
                            {"$ref": f"#/$defs/{state_name}"},
                            {
                                "required": ["state_type"],
                                "properties": {"state_type": {"const": slot}},
                            },
                        ]
                    },
                ],
                "default": None,
            }

gov_name = next((x for x in ("governance", "governanceState") if x in defs), "governance")
gov = defs.setdefault(gov_name, {"type": "object", "properties": {}, "additionalProperties": False})
gp = gov.setdefault("properties", {})
status_key = next((x for x in ("approval_state", "status", "decision") if x in gp), "approval_state")
gp.setdefault(status_key, {"enum": ["unreviewed", "proposed", "approved", "rejected"]})
gp.setdefault("approved_by", {"type": ["string", "null"], "minLength": 1})
gp.setdefault("approved_at", {"type": ["string", "null"], "format": "date-time"})
gp.setdefault("approval_evidence_hash", {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"})
gov.setdefault("allOf", [])
gov["allOf"] = [x for x in gov["allOf"] if x.get("$comment") != "phase013-approval"]
gov["allOf"].append({
    "$comment": "phase013-approval",
    "if": {"required": [status_key], "properties": {status_key: {"const": "approved"}}},
    "then": {
        "required": ["approved_by", "approved_at", "approval_evidence_hash"],
        "properties": {
            "approved_by": {"type": "string", "minLength": 1},
            "approved_at": {"type": "string", "format": "date-time"},
            "approval_evidence_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    },
})
write("schemas/canonical-schedule.schema.json", canon)

# Execution record schema.
execution = load("schemas/execution-record.schema.json")
ed = execution.setdefault("$defs", {})
ed["objectiveVector"] = {
    "type": "array",
    "minItems": 7,
    "maxItems": 7,
    "prefixItems": [{"type": "integer"} for _ in range(7)],
    "items": False,
}
replace_objective_vectors(execution, "#/$defs/objectiveVector")
for key in ("executed_at", "created_at", "validated_at"):
    if key in execution.get("properties", {}):
        execution["properties"][key]["format"] = "date-time"
execution.setdefault("allOf", [])
execution["allOf"] = [x for x in execution["allOf"] if x.get("$comment") not in {"phase013-pass", "phase013-nonexecuted"}]
execution["allOf"].extend([
    {
        "$comment": "phase013-pass",
        "if": {"required": ["status"], "properties": {"status": {"const": "executed_pass"}}},
        "then": {
            "required": ["feasibility_status", "optimality_status", "validator_status", "objective_vector"],
            "properties": {
                "feasibility_status": {"const": "feasible"},
                "optimality_status": {"not": {"const": "infeasible"}},
                "validator_status": {"const": "pass"},
            },
        },
    },
    {
        "$comment": "phase013-nonexecuted",
        "if": {
            "required": ["status"],
            "properties": {
                "status": {
                    "enum": [
                        "not_executed", "not_accessible", "native_validation_required",
                        "practitioner_validation_required", "buyer_validation_required",
                    ]
                }
            },
        },
        "then": {"properties": {"input_hash": {"type": "null"}}},
    },
])


def strengthen_native(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "status" in props and "system" in props:
            values = props.get("status", {}).get("enum", [])
            attempted = [x for x in ("attempted", "executed") if x in values]
            if attempted:
                node.setdefault("allOf", [])
                node["allOf"] = [x for x in node["allOf"] if x.get("$comment") != "phase013-native"]
                node["allOf"].append({
                    "$comment": "phase013-native",
                    "if": {"required": ["status"], "properties": {"status": {"enum": attempted}}},
                    "then": {
                        "required": ["system"],
                        "properties": {
                            "system": {
                                "type": "string",
                                "enum": ["primavera_p6", "microsoft_project"],
                            }
                        },
                    },
                })
        for value in node.values():
            strengthen_native(value)
    elif isinstance(node, list):
        for value in node:
            strengthen_native(value)


strengthen_native(execution)
write("schemas/execution-record.schema.json", execution)

# Structured explanation schema.
explanation = load("schemas/structured-explanation.schema.json")
xd = explanation.setdefault("$defs", {})
xd["objectiveVector"] = ed["objectiveVector"]
replace_objective_vectors(explanation, "#/$defs/objectiveVector")
xd["calculationTrace"] = {
    "type": "object",
    "required": ["rule_id", "input_entity_ids", "derived_start", "derived_finish", "validator_status", "recomputation_hash"],
    "properties": {
        "rule_id": {"type": "string", "minLength": 1},
        "input_entity_ids": {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "derived_start": {"type": ["integer", "null"]},
        "derived_finish": {"type": ["integer", "null"]},
        "validator_status": {"const": "pass"},
        "recomputation_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "additionalProperties": False,
}
explanation.setdefault("properties", {})["calculation_trace"] = {
    "anyOf": [{"$ref": "#/$defs/calculationTrace"}, {"type": "null"}],
    "default": None,
}
disc = next((x for x in ("explanation_scope", "explanation_type", "kind") if x in explanation["properties"]), None)
if disc:
    values = explanation["properties"][disc].get("enum", [])
    calc = [x for x in values if "calculation" in str(x) or x == "trace"]
    if calc:
        explanation.setdefault("allOf", [])
        explanation["allOf"] = [x for x in explanation["allOf"] if x.get("$comment") != "phase013-trace"]
        explanation["allOf"].append({
            "$comment": "phase013-trace",
            "if": {"required": [disc], "properties": {disc: {"enum": calc}}},
            "then": {
                "required": ["governing_entity_id", "calculation_trace"],
                "properties": {
                    "governing_entity_id": {"type": "string", "minLength": 1},
                    "calculation_trace": {"$ref": "#/$defs/calculationTrace"},
                },
            },
        })


def strengthen_counterfactual(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "feasibility_status" in props:
            node.setdefault("allOf", [])
            node["allOf"] = [x for x in node["allOf"] if x.get("$comment") != "phase013-counterfactual"]
            node["allOf"].append({
                "$comment": "phase013-counterfactual",
                "if": {"required": ["feasibility_status"], "properties": {"feasibility_status": {"const": "feasible"}}},
                "then": {
                    "required": ["output_hash", "validator_status"],
                    "properties": {
                        "output_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "validator_status": {"const": "pass"},
                    },
                },
            })
        for value in node.values():
            strengthen_counterfactual(value)
    elif isinstance(node, list):
        for value in node:
            strengthen_counterfactual(value)


strengthen_counterfactual(explanation)
write("schemas/structured-explanation.schema.json", explanation)

# Exact profile/policy values are generated into the validator at amendment time.
profiles = sorted((ROOT / "config").glob("deterministic-execution-profile-*.json"))
objectives = sorted((ROOT / "config").glob("objective-policy-*.json"))
if not profiles or not objectives:
    raise SystemExit("Required profile or objective policy missing")
profile_path = profiles[-1].relative_to(ROOT).as_posix()
objective_path = objectives[-1].relative_to(ROOT).as_posix()
profile = json.loads(profiles[-1].read_text(encoding="utf-8"))
objective = json.loads(objectives[-1].read_text(encoding="utf-8"))

followup = f'''from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

REQUIRED_REGISTERS = {{
    "comparator-run-register.csv", "evidence-register.csv", "experiment-register.csv",
    "input-economics-log.csv", "native-roundtrip-diff.csv",
    "semantic-compatibility-matrix.csv", "source-quality-contradiction-register.csv",
}}
PROFILE_PATH = {profile_path!r}
OBJECTIVE_PATH = {objective_path!r}
EXPECTED_PROFILE = {profile!r}
EXPECTED_OBJECTIVE = {objective!r}


def _rows(state):
    if not isinstance(state, dict):
        return []
    if isinstance(state.get("state"), dict):
        state = state["state"]
    for key in ("activities", "activity_states"):
        if isinstance(state.get(key), list):
            return [x for x in state[key] if isinstance(x, dict)]
    return []


def _resource_refs(row):
    out = []
    for key in ("resource_assignments", "assignments"):
        for value in row.get(key, []) if isinstance(row.get(key, []), list) else []:
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, dict) and isinstance(value.get("resource_id"), str):
                out.append(value["resource_id"]
                )
    return out


def validate_schedule(schedule: dict[str, Any], label: str) -> list[str]:
    errors = []
    activities = [x for x in schedule.get("activities", []) if isinstance(x, dict)]
    activity_ids = {{x.get("id") for x in activities}}
    resource_ids = {{x.get("id") for x in schedule.get("resources", []) if isinstance(x, dict)}}
    horizon = schedule.get("time_axis", {{}}).get("horizon")
    for slot in ("baseline", "approved_forecast", "proposed_scenario"):
        state = schedule.get(slot)
        if state is None:
            continue
        raw = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else state
        if isinstance(raw, dict) and raw.get("state_type") != slot:
            errors.append(f"{{label}}: {{slot}} has wrong state_type")
        rows = _rows(state)
        ids = []
        for row in rows:
            aid = row.get("activity_id")
            ids.append(aid)
            if aid not in activity_ids:
                errors.append(f"{{label}}: {{slot}} references unknown activity {{aid}}")
            start, finish = row.get("start"), row.get("finish")
            if isinstance(start, int) and isinstance(finish, int) and start > finish:
                errors.append(f"{{label}}: {{slot}} activity {{aid}} has start after finish")
            if isinstance(horizon, int):
                for name, value in (("start", start), ("finish", finish)):
                    if isinstance(value, int) and not 0 <= value <= horizon:
                        errors.append(f"{{label}}: {{slot}} activity {{aid}} {{name}} outside horizon")
            for rid in _resource_refs(row):
                if rid not in resource_ids:
                    errors.append(f"{{label}}: {{slot}} activity {{aid}} references unknown resource {{rid}}")
        if len(ids) != len(set(ids)):
            errors.append(f"{{label}}: {{slot}} contains duplicate activity states")
        if slot == "proposed_scenario" and set(ids) != activity_ids:
            errors.append(f"{{label}}: proposed_scenario must cover every activity exactly once")

    wbs = [x for x in schedule.get("wbs", []) if isinstance(x, dict)]
    parent = {{x.get("id"): x.get("parent_id") for x in wbs}}
    visiting, visited = set(), set()
    def visit(node, trail):
        if node in visiting:
            errors.append(f"{{label}}: WBS cycle detected")
            return
        if node in visited or node not in parent:
            return
        visiting.add(node)
        p = parent[node]
        if isinstance(p, str):
            visit(p, trail + [node])
        visiting.remove(node)
        visited.add(node)
    for node in sorted(x for x in parent if isinstance(x, str)):
        visit(node, [])

    for activity in activities:
        if activity.get("actual_start") is not None and activity.get("actual_finish") is None and activity.get("remaining_duration") is None:
            errors.append(f"{{label}}: in-progress activity {{activity.get('id')}} lacks remaining_duration")
        frozen = activity.get("frozen_state")
        if isinstance(frozen, dict) and (frozen.get("is_frozen") is True or frozen.get("frozen") is True):
            start = next((frozen.get(k) for k in ("fixed_start", "frozen_start", "start") if k in frozen), None)
            finish = next((frozen.get(k) for k in ("fixed_finish", "frozen_finish", "finish") if k in frozen), None)
            if not isinstance(start, int) or not isinstance(finish, int):
                errors.append(f"{{label}}: frozen activity {{activity.get('id')}} lacks coordinates")
            elif start > finish:
                errors.append(f"{{label}}: frozen activity {{activity.get('id')}} has reversed coordinates")

    for constraint in schedule.get("operational_constraints", []):
        if not isinstance(constraint, dict):
            continue
        pairs = []
        for a, b in (("window_start", "window_finish"), ("start", "finish"), ("earliest_start", "latest_finish")):
            if a in constraint or b in constraint:
                pairs.append((constraint.get(a), constraint.get(b)))
        if isinstance(constraint.get("window"), dict):
            pairs.append((constraint["window"].get("start"), constraint["window"].get("finish")))
        for start, finish in pairs:
            if not isinstance(start, int) or not isinstance(finish, int) or start >= finish:
                errors.append(f"{{label}}: invalid operational-constraint window")
            elif isinstance(horizon, int) and not 0 <= start < finish <= horizon:
                errors.append(f"{{label}}: operational-constraint window outside horizon")

    governance = schedule.get("governance")
    if isinstance(governance, dict):
        state = governance.get("approval_state", governance.get("status", governance.get("decision")))
        if state == "approved":
            for key in ("approved_by", "approved_at", "approval_evidence_hash"):
                if not isinstance(governance.get(key), str) or not governance[key]:
                    errors.append(f"{{label}}: approved governance lacks {{key}}")
    return errors


def validate_followup(root: Path) -> list[str]:
    errors = []
    if json.loads((root / PROFILE_PATH).read_text(encoding="utf-8")) != EXPECTED_PROFILE:
        errors.append("Deterministic execution profile differs from its frozen value contract")
    if json.loads((root / OBJECTIVE_PATH).read_text(encoding="utf-8")) != EXPECTED_OBJECTIVE:
        errors.append("Objective policy differs from its frozen value contract")
    present = {{p.name for p in (root / "registers").glob("*.csv")}}
    missing = sorted(REQUIRED_REGISTERS - present)
    if missing:
        errors.append(f"Required registers are missing: {{missing}}")
    with (root / "benchmarks/semantic/catalogue.csv").open("r", encoding="utf-8", newline="") as f:
        catalogue = {{r.get("case_id"): r for r in csv.DictReader(f)}}
    for path in sorted((root / "benchmarks/semantic/cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        row = catalogue.get(case.get("case_id"))
        if row is None:
            errors.append(f"{{path.name}}: no catalogue row")
        else:
            for field in ("title", "category", "purpose"):
                if field in row and row.get(field, "") != str(case.get(field, "")):
                    errors.append(f"{{path.name}}: catalogue {{field}} differs from fixture")
        schedule = case.get("schedule", {{}})
        errors.extend(validate_schedule(schedule, path.name))
        if schedule.get("project", {{}}).get("progress_policy") == "actual_dates" and case.get("expected", {{}}).get("reference_status") == "declared":
            errors.append(f"{{path.name}}: actual_dates must be native_validation_only")
    return errors
'''
(ROOT / "tools/followup_validation.py").write_text(followup, encoding="utf-8", newline="\n")

semantics = '''from __future__ import annotations

OBJECTIVE_VECTOR_LENGTH = 7


def _vector(value, label):
    if not isinstance(value, list) or len(value) != OBJECTIVE_VECTOR_LENGTH or any(type(x) is not int for x in value):
        return [f"{label} must contain exactly seven integers"]
    return []


def validate_execution_record(record):
    errors = []
    if record.get("status") == "executed_pass":
        if record.get("feasibility_status") != "feasible":
            errors.append("executed_pass requires feasible status")
        if record.get("optimality_status") == "infeasible":
            errors.append("executed_pass cannot be infeasible")
        errors.extend(_vector(record.get("objective_vector"), "objective_vector"))
    if record.get("status") in {"not_executed", "not_accessible", "native_validation_required", "practitioner_validation_required", "buyer_validation_required"} and record.get("input_hash") is not None:
        errors.append("non-executed status requires input_hash=null")
    rt = record.get("native_round_trip")
    if isinstance(rt, dict) and rt.get("status") in {"attempted", "executed"} and rt.get("system") not in {"primavera_p6", "microsoft_project"}:
        errors.append("attempted native round trip requires a real system")
    return errors


def validate_explanation(record):
    errors = []
    previous, proposed = record.get("previous_start"), record.get("proposed_start")
    if isinstance(previous, int) and isinstance(proposed, int) and record.get("movement") != proposed - previous:
        errors.append("movement must equal proposed_start - previous_start")
    if "selected_objective_vector" in record:
        errors.extend(_vector(record.get("selected_objective_vector"), "selected_objective_vector"))
    for i, item in enumerate(record.get("counterfactuals", [])):
        if isinstance(item, dict) and item.get("feasibility_status") == "feasible":
            if not isinstance(item.get("output_hash"), str) or len(item["output_hash"]) != 64:
                errors.append(f"counterfactuals[{i}] lacks output_hash")
            if item.get("validator_status") != "pass":
                errors.append(f"counterfactuals[{i}] requires validator_status=pass")
    return errors
'''
(ROOT / "tools/evidence_semantics.py").write_text(semantics, encoding="utf-8", newline="\n")

validator = ROOT / "tools/validate_phase0.py"
source = validator.read_text(encoding="utf-8")
source = source.replace("from jsonschema import Draft202012Validator\n", "from jsonschema import Draft202012Validator, FormatChecker\n")
if "from followup_validation import validate_followup" not in source:
    source = source.replace("from referencing import Registry, Resource\n", "from referencing import Registry, Resource\n\nfrom followup_validation import validate_followup\n")
source = source.replace(
    "Draft202012Validator(case_schema, registry=registry)",
    "Draft202012Validator(case_schema, registry=registry, format_checker=FormatChecker())",
)
if "errors += validate_followup(ROOT)" not in source:
    source = source.replace("    if errors:\n", "    errors += validate_followup(ROOT)\n\n    if errors:\n", 1)
validator.write_text(source, encoding="utf-8", newline="\n")

# Focused regression tests for the second-review invariants.
test_source = '''from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_semantics import validate_execution_record, validate_explanation
from followup_validation import validate_schedule


class RemainingReviewGuards(unittest.TestCase):
    def test_execution_coherence_and_vector(self):
        errors = validate_execution_record({"status": "executed_pass", "feasibility_status": "feasible", "optimality_status": "infeasible", "objective_vector": [0]})
        self.assertTrue(any("infeasible" in x for x in errors))
        self.assertTrue(any("seven" in x for x in errors))

    def test_nonexecuted_hash_and_native_system(self):
        self.assertTrue(validate_execution_record({"status": "not_accessible", "input_hash": "a" * 64}))
        self.assertTrue(validate_execution_record({"status": "not_executed", "input_hash": None, "native_round_trip": {"status": "attempted", "system": None}}))

    def test_derived_movement_and_counterfactual_evidence(self):
        self.assertTrue(validate_explanation({"previous_start": 2, "proposed_start": 8, "movement": 5}))
        self.assertGreaterEqual(len(validate_explanation({"counterfactuals": [{"feasibility_status": "feasible"}]})), 2)

    def test_wbs_cycle(self):
        schedule = {"activities": [], "resources": [], "wbs": [{"id": "A", "parent_id": "B"}, {"id": "B", "parent_id": "C"}, {"id": "C", "parent_id": "A"}]}
        self.assertTrue(any("WBS cycle" in x for x in validate_schedule(schedule, "case")))

    def test_in_progress_remaining_duration(self):
        schedule = {"activities": [{"id": "A", "actual_start": 1, "actual_finish": None}], "resources": []}
        self.assertTrue(any("remaining_duration" in x for x in validate_schedule(schedule, "case")))

    def test_scenario_coverage_resource_and_interval(self):
        schedule = {"activities": [{"id": "A"}, {"id": "B"}], "resources": [{"id": "R1"}], "proposed_scenario": {"state_type": "proposed_scenario", "activities": [{"activity_id": "A", "start": 3, "finish": 2, "resource_assignments": [{"resource_id": "R2"}]}]}}
        errors = validate_schedule(schedule, "case")
        self.assertTrue(any("cover every" in x for x in errors))
        self.assertTrue(any("unknown resource" in x for x in errors))
        self.assertTrue(any("start after finish" in x for x in errors))

    def test_operational_window_frozen_and_approval(self):
        schedule = {"time_axis": {"horizon": 10}, "activities": [{"id": "A", "frozen_state": {"is_frozen": True}}], "resources": [], "operational_constraints": [{"id": "C", "window_start": 8, "window_finish": 2}], "governance": {"approval_state": "approved"}}
        errors = validate_schedule(schedule, "case")
        self.assertTrue(any("frozen" in x for x in errors))
        self.assertTrue(any("operational" in x for x in errors))
        self.assertTrue(any("approved" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
'''
(ROOT / "tests/test_phase0_remaining_guards.py").write_text(test_source, encoding="utf-8", newline="\n")

(ROOT / "docs/amendments").mkdir(parents=True, exist_ok=True)
amendment = """# Phase 0 Amendment 0.1.3 — Remaining Codex Review Corrections

This amendment closes the second automated review without expanding the Phase 0 scope. It adds machine-enforced invariants for calculation traces, counterfactual evidence, typed schedule states, frozen coordinates, complete scenario coverage, resource references, ordered intervals, WBS cycles, in-progress duration, derived movement, objective-vector shape, exact policy/profile values, native-only actual-dates cases, catalogue parity, the complete register set, native round-trip targets, and approval evidence.

No CPM engine, optimiser, native compatibility claim, UI, or production system is introduced.
"""
(ROOT / "docs/amendments/phase0-0.1.3-remaining-review-corrections.md").write_text(amendment, encoding="utf-8", newline="\n")

for rel, heading, body in [
    ("docs/03-canonical-schedule-model.md", "## Phase 0.1.3 state invariants", "Every persisted state is typed; proposed scenarios cover all activities; state resource references and intervals are validated; frozen work carries coordinates; and approvals carry actor, timestamp, and evidence hash."),
    ("docs/04-deterministic-contract.md", "## Phase 0.1.3 evidence invariants", "Profile and policy files are compared by complete value. Objective vectors contain exactly seven integer levels. Movement is recomputed, and feasible counterfactuals retain validated output evidence."),
    ("docs/06-benchmark-protocol.md", "## Phase 0.1.3 preregistration guards", "Catalogue metadata, required registers, WBS hierarchy, operational windows, actual-dates classification, and proposed-scenario coverage are validated before execution."),
]:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if heading not in text:
        path.write_text(text.rstrip() + f"\n\n{heading}\n\n{body}\n", encoding="utf-8", newline="\n")

consolidated = ROOT / "PHASE-0-PROTOCOL-CONSOLIDATED.md"
text = consolidated.read_text(encoding="utf-8")
if "Phase 0 Amendment 0.1.3" not in text:
    consolidated.write_text(text.rstrip() + "\n\n---\n\n" + amendment, encoding="utf-8", newline="\n")

pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
text = re.sub(r'(?m)^version\s*=\s*"[^"]+"', 'version = "0.1.3"', text, count=1)
pyproject.write_text(text, encoding="utf-8", newline="\n")

changelog = ROOT / "CHANGELOG.md"
text = changelog.read_text(encoding="utf-8")
if "## 0.1.3" not in text:
    marker = text.find("\n") + 1 if text.startswith("#") else 0
    entry = "\n## 0.1.3 — Remaining review corrections\n\n- Close the remaining second-review schema and semantic guardrails.\n- Add negative regression coverage and exact policy/profile value freezing.\n\n"
    text = text[:marker] + entry + text[marker:].lstrip("\n")
    changelog.write_text(text, encoding="utf-8", newline="\n")

print("Phase 0.1.3 review fixes applied")
