from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
CASES = ROOT / "benchmarks" / "semantic" / "cases"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_cases() -> list[str]:
    errors: list[str] = []
    case_schema = load_json(SCHEMAS / "semantic-test-case.schema.json")
    canonical = load_json(SCHEMAS / "canonical-schedule.schema.json")
    registry = Registry().with_resource(
        "https://example.invalid/dsc/canonical-schedule.schema.json",
        Resource.from_contents(canonical),
    )
    validator = Draft202012Validator(case_schema, registry=registry)

    case_files = sorted(CASES.glob("*.json"))
    if len(case_files) != 50:
        errors.append(f"Expected 50 case files, found {len(case_files)}")

    seen: set[str] = set()
    for path in case_files:
        data = load_json(path)
        cid = data.get("case_id", "<missing>")
        if cid in seen:
            errors.append(f"Duplicate case_id: {cid}")
        seen.add(cid)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            location = ".".join(str(p) for p in err.path)
            errors.append(f"{path.name}:{location}: {err.message}")

        schedule = data.get("schedule", {})
        acts = schedule.get("activities", [])
        rels = schedule.get("relationships", [])
        cals = {c.get("id") for c in schedule.get("calendars", [])}
        resources = {r.get("id") for r in schedule.get("resources", [])}
        act_ids = [a.get("id") for a in acts]
        if len(act_ids) != len(set(act_ids)):
            errors.append(f"{path.name}: duplicate activity ID")
        for a in acts:
            if a.get("calendar_id") not in cals:
                errors.append(f"{path.name}: unknown activity calendar {a.get('calendar_id')}")
            for assn in a.get("assignments", []):
                if assn.get("resource_id") not in resources:
                    errors.append(f"{path.name}: unknown resource {assn.get('resource_id')}")
        for r in schedule.get("resources", []):
            if r.get("calendar_id") not in cals:
                errors.append(f"{path.name}: unknown resource calendar {r.get('calendar_id')}")
        for rel in rels:
            if rel.get("predecessor_id") not in act_ids or rel.get("successor_id") not in act_ids:
                errors.append(f"{path.name}: relationship references unknown activity")

    catalogue = ROOT / "benchmarks" / "semantic" / "catalogue.csv"
    with catalogue.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 50:
        errors.append(f"Expected 50 catalogue rows, found {len(rows)}")
    if {r["case_id"] for r in rows} != seen:
        errors.append("Catalogue case IDs do not match fixture case IDs")
    return errors


def validate_registers() -> list[str]:
    errors: list[str] = []
    for path in sorted((ROOT / "registers").glob("*.csv")):
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) != 1 or not rows[0] or any(not h for h in rows[0]):
            errors.append(f"{path.name}: expected exactly one non-empty header row")
    return errors


def validate_manifest() -> list[str]:
    errors: list[str] = []
    manifest = ROOT / "manifest.sha256"
    if not manifest.exists():
        return ["manifest.sha256 is missing"]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        path = ROOT / rel
        if not path.exists():
            errors.append(f"Manifest path missing: {rel}")
        elif sha256(path) != digest:
            errors.append(f"Manifest hash mismatch: {rel}")
    return errors


def main() -> int:
    errors = validate_cases() + validate_registers() + validate_manifest()
    if errors:
        print("PHASE 0 VALIDATION: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PHASE 0 VALIDATION: PASS")
    print("- 50 unique semantic fixtures validated")
    print("- Canonical and test-case schemas resolved")
    print("- Cross-reference checks passed")
    print("- Register headers validated")
    print("- SHA-256 manifest verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
