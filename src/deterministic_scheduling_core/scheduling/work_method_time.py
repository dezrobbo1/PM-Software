"""Joint authorised structure, productive placements and selective allocation.

This owns a bounded future-only composition path. Existing elapsed scheduling and
accepted-progress workspaces remain unchanged. Controls live outside this module.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from math import prod
from time import perf_counter
from typing import Any

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import WorkPackage
from deterministic_scheduling_core.project.planning_workspace import digest, validate as validate_workspace
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, from_document, input_hash, materialise, membership,
    method_selections, structural_view, to_document,
)
from deterministic_scheduling_core.resource_allocation_repair_experiment import check_allocation
from .engine import validate_project
from .planning_workspace import _case, _group_placements
from .canonical_batching import (
    MAX_SAFE_BLOCK_VALUE, CanonicalBlock, CanonicalDigit, build_lexicographic_blocks,
)

PLAN_SCHEMA = "pm-native-work-method-time-plan/0"
POLICY = "finish-global-start-timing-declared-methods-declared-modes-canonical-placement/0"
MAX_DETERMINISTIC_TIME_PER_STAGE = 60.0
MAX_WORKFACE_INTERVALS = 20_000


@dataclass(frozen=True)
class WorkMethodTimeResult:
    plan: dict
    metrics: dict


@dataclass(frozen=True)
class _Stage:
    name: str
    stage_type: str
    expression: Any
    maximum: int


@dataclass
class _CompiledWorkMethodTime:
    problem: WorkMethodTimeProject
    environment: Any
    specs: dict
    model: cp_model.CpModel
    source: dict
    members: dict
    methods: dict
    starts: dict
    ends: dict
    mode_vars: dict
    choices: dict
    stages: tuple[_Stage, ...]
    placement_count: int
    workface_interval_count: int
    started_at: float
    built_at: float
    compile_metrics: dict


def validate_problem(problem: WorkMethodTimeProject) -> None:
    """Use the existing two native validators; reject unsupported composition.

    Enumerating graph projections here checks admission only. The candidate does
    not solve or rank those graphs separately. All definitions, including inactive
    methods, are validated; infeasible availability is not malformed structure.
    """
    if not isinstance(problem, WorkMethodTimeProject):
        raise ValueError("expected WorkMethodTimeProject, not a statused workspace")
    from_document(to_document(problem))
    source = problem.project
    if not isinstance(source.get("activities"), list) or not 1 <= len(source["activities"]) <= 64:
        raise ValueError("bounded composition requires 1..64 declared activities")
    if type(source.get("horizon_ticks")) is not int or not 1 <= source["horizon_ticks"] <= 480:
        raise ValueError("bounded composition requires a 1..480 tick horizon")
    if any(not isinstance(p, WorkPackage) for p in problem.work_packages):
        raise ValueError("structure must use native WorkPackage definitions")
    if prod(len(p.methods) for p in problem.work_packages) > 16:
        raise ValueError("bounded admission supports at most 16 authorised structures")
    for package in problem.work_packages:
        if not isinstance(package.id, str) or not package.id.strip():
            raise ValueError("nonempty work-package ID required")
        for method in package.methods:
            if not isinstance(method.id, str) or not method.id.strip():
                raise ValueError("nonempty execution-method ID required")
    validate_project(structural_view(problem))
    for selected in method_selections(problem):
        validate_workspace(materialise(problem, selected), allow_future_constraints=True)
    members = membership(problem)
    fixed_packages = {package.id for package in problem.work_packages if len(package.methods) == 1}
    for activity in source["activities"]:
        latest = activity.get("latest_finish")
        owner = members.get(activity["id"])
        if latest is not None and (owner is None or owner[0] in fixed_packages):
            if activity.get("not_before", 0) + min(m["processing_ticks"] for m in activity["modes"]) > latest:
                raise ValueError(f"{activity['id']}: fixed activity cannot finish by latest_finish from not_before")


def _mode_cases(problem: WorkMethodTimeProject):
    """Reuse native productive compilation, with no fixed-method solve."""
    source = problem.project
    union_workspace = {"project": source, "reports": list(problem.reports)}
    first = {a["id"]: a["modes"][0]["id"] for a in source["activities"]}
    environment = _case(union_workspace, first)
    specs = {}
    for activity in source["activities"]:
        for mode in activity["modes"]:
            selected = {**first, activity["id"]: mode["id"]}
            specs[activity["id"], mode["id"]] = _case(union_workspace, selected).activity_by_id[activity["id"]]
    # Named physical requirements remain explicit in this composition path.
    # Genuine identity-free capacity is represented by resource_groups, whose
    # anonymous unit choice is held consistently across all productive segments.
    return environment, specs


def policy_key(problem: WorkMethodTimeProject, selected_methods: dict,
               selected_modes: dict, objective) -> tuple:
    """Comparable policy, independent of inactive-method placeholders in controls."""
    methods = tuple(next(i for i, m in enumerate(p.methods) if m.id == selected_methods[p.id])
                    for p in problem.work_packages)
    modes = tuple(next(i + 1 for i, m in enumerate(a["modes"]) if m["id"] == selected_modes[a["id"]])
                  if a["id"] in selected_modes else 0 for a in problem.project["activities"])
    return tuple(objective), methods, modes


def _hash_plan(plan: dict) -> str:
    return digest({key: value for key, value in plan.items() if key != "plan_hash"})


def _validate_physics(problem: WorkMethodTimeProject, plan: dict):
    selected_methods, selected_modes = plan["selected_methods"], plan["selected_modes"]
    workspace = materialise(problem, selected_methods)
    active = {a["id"]: a for a in workspace["project"]["activities"]}
    if not isinstance(selected_modes, dict) or set(selected_modes) != set(active):
        raise ValueError("selected modes must cover exactly the active structure")
    for aid, mode_id in selected_modes.items():
        if mode_id not in {m["id"] for m in active[aid]["modes"]}:
            raise ValueError(f"{aid}: unauthorised activity mode")
    case = _case(workspace, selected_modes)
    if plan["pooled_riggers"] is not False:
        raise ValueError("named physical requirements must remain explicit in this composition")
    entries = plan["entries"]
    if not isinstance(entries, list) or len(entries) != len(active) or {
        e["activity_id"] for e in entries
    } != set(active):
        raise ValueError("entries must cover exactly the selected method activities")
    witness = {}
    for row in plan["allocation_witness"]:
        if not isinstance(row, list) or len(row) != 3 or not all(isinstance(v, str) for v in row):
            raise ValueError("invalid named allocation witness")
        key = row[0], row[1]
        if key in witness:
            raise ValueError("duplicate allocation witness slot")
        witness[key] = row[2]
    expected_named = {(a.id, r.id) for a in case.activities for r in a.requirements
                      if not r.id.startswith("@group/")}
    if set(witness) != expected_named:
        raise ValueError("named witness must cover exactly the active named requirements")
    members = membership(problem)
    raw = []
    for entry in entries:
        if set(entry) != {"activity_id", "mode_id", "work_package_id", "method_id",
                          "start", "finish", "periods", "assignments", "group_demands"}:
            raise ValueError("unsupported plan entry fields")
        aid = entry["activity_id"]
        latest = active[aid].get("latest_finish")
        if latest is not None and entry["finish"] > latest:
            raise ValueError(f"{aid}: active finish exceeds latest_finish")
        if (entry["mode_id"] != selected_modes[aid]
                or (entry["work_package_id"], entry["method_id"]) != members.get(aid, (None, None))):
            raise ValueError("entry has incorrect mode/structure ownership")
        mode = next(m for m in active[aid]["modes"] if m["id"] == selected_modes[aid])
        expected_demands = [[d["group_id"], d["demand"]] for d in mode.get("group_requirements", [])]
        if entry["group_demands"] != expected_demands:
            raise ValueError("incorrect native group quantities")
        spec = case.activity_by_id[aid]
        named = tuple(r for r in spec.requirements if not r.id.startswith("@group/"))
        assignments = dict(entry["assignments"])
        if len(assignments) != len(entry["assignments"]) or set(assignments) != {r.id for r in named}:
            raise ValueError("incorrect named requirement coverage")
        for requirement in named:
            rid = assignments[requirement.id]
            if rid is None:
                raise ValueError("named requirements must retain explicit whole-activity assignment")
            if rid != witness[aid, requirement.id]:
                raise ValueError("submitted allocation and witness disagree")
        raw.append(ra.ScheduledEntry(aid, entry["start"], entry["finish"],
                                    tuple(tuple(p) for p in entry["periods"]),
                                    tuple((r.id, None if r.id.startswith("@group/") else witness[aid, r.id])
                                          for r in spec.requirements)))
    workfaces = {}
    for entry in entries:
        for group in active[entry["activity_id"]].get("exclusion_groups", []):
            for other in workfaces.get(group, []):
                if (entry["start"] < entry["finish"] and other["start"] < other["finish"]
                        and entry["start"] < other["finish"] and other["start"] < entry["finish"]):
                    raise ValueError(f"{group}: active workface execution envelopes overlap")
            workfaces.setdefault(group, []).append(entry)
    check = check_allocation(case, tuple(raw))
    if check.status != ra.EXACT_FEASIBLE:
        raise ValueError(f"independent physical validation failed: {check.reason}")
    # Cross-check the independently allocated group units with the older checker.
    allocated = {(aid, slot): rid for aid, slot, rid in check.witness}
    explicit = tuple(replace(e, assignments=tuple((slot, allocated[e.activity_id, slot])
                                                  for slot, _ in e.assignments)) for e in raw)
    legacy = ra.check_fixed_schedule(case, explicit)
    if not legacy.physically_assignable:
        raise ValueError(f"existing physical checker rejected result: {legacy.reason}")
    weights = {a["id"]: i + 1 for i, a in enumerate(problem.project["activities"])}
    by_id = {e.activity_id: e for e in raw}
    objective = [by_id[case.objective_activity_id].finish,
                 sum(weights[e.activity_id] * e.start for e in raw)]
    if plan["objective"] != objective:
        raise ValueError("incorrect finish/global timing objective")
    return check


def validate_plan(problem: WorkMethodTimeProject, plan: dict) -> str:
    """Validate structure, accounting and executability without solving a schedule.

    A hash is identity/integrity evidence, not authentication or an independent
    optimality certificate. Optimality is reported by the producing solver stages.
    """
    validate_problem(problem)
    if not isinstance(plan, dict) or set(plan) != {
        "schema", "input_hash", "policy", "selected_methods", "selected_modes", "entries",
        "objective", "pooled_riggers", "allocation_witness", "physical_status", "solver", "plan_hash"
    } or plan["schema"] != PLAN_SCHEMA:
        raise ValueError("unsupported composition plan")
    if plan["input_hash"] != input_hash(problem) or plan["policy"] != POLICY:
        raise ValueError("plan belongs to different inputs or policy")
    if plan["plan_hash"] != _hash_plan(plan):
        raise ValueError("composition plan hash mismatch")
    if plan["physical_status"] != ra.EXACT_FEASIBLE:
        raise ValueError("plan does not claim a physical witness")
    _validate_physics(problem, plan)
    return ra.EXACT_FEASIBLE


def _compile_work_method_time(problem: WorkMethodTimeProject) -> _CompiledWorkMethodTime:
    """Build the shared bounded model and retain additive phase measurements."""
    started = perf_counter()
    problem = deepcopy(problem)
    input_copy_ms = (perf_counter() - started) * 1000
    validation_started = perf_counter()
    validate_problem(problem)
    validation_ms = (perf_counter() - validation_started) * 1000
    cases_started = perf_counter()
    environment, specs = _mode_cases(problem)
    productive_case_compile_ms = (perf_counter() - cases_started) * 1000
    assembly_started = perf_counter()
    model = cp_model.CpModel()
    source = problem.project
    members = membership(problem)
    methods = {(p.id, m.id): model.new_bool_var(f"method_{i}_{j}")
               for i, p in enumerate(problem.work_packages) for j, m in enumerate(p.methods)}
    for package in problem.work_packages:
        model.add_exactly_one([methods[package.id, m.id] for m in package.methods])
    starts, ends, presence, mode_vars, choices = {}, {}, {}, {}, {}
    named_intervals = {r.id: [] for r in environment.resources}
    workface_intervals = {}
    placement_count = 0
    workface_interval_count = 0
    placement_generation_ms = 0.0
    for ai, activity in enumerate(source["activities"]):
        aid = activity["id"]
        present = methods[members[aid]] if aid in members else model.new_constant(1)
        presence[aid] = present
        starts[aid] = model.new_int_var(0, environment.horizon, f"start_{ai}")
        ends[aid] = model.new_int_var(0, environment.horizon, f"end_{ai}")
        choices[aid] = []
        for mi, mode in enumerate(activity["modes"]):
            mid = mode["id"]
            mode_var = model.new_bool_var(f"mode_{ai}_{mi}")
            mode_vars[aid, mid] = mode_var
            spec = specs[aid, mid]
            placement_started = perf_counter()
            placements = _group_placements(environment, spec, "B")
            if "latest_finish" in activity:
                placements = tuple(p for p in placements if p.finish <= activity["latest_finish"])
            placements = tuple(sorted(placements, key=lambda p: (
                p.start, p.finish, p.periods, tuple("" if r is None else r for r in p.assignments))))
            placement_generation_ms += (perf_counter() - placement_started) * 1000
            placement_count += len(placements)
            if placement_count > 20000:
                raise ValueError("bounded composition supports at most 20000 placement alternatives")
            # Multiple group names multiply optional intervals per placement.
            # Bound that expansion before constructing any of this mode's intervals.
            active_placements = sum(p.start < p.finish for p in placements)
            workface_interval_count += active_placements * len(activity.get("exclusion_groups", []))
            if workface_interval_count > MAX_WORKFACE_INTERVALS:
                raise ValueError("bounded composition supports at most 20000 workface intervals")
            literals = []
            for pi, placement in enumerate(placements):
                literal = model.new_bool_var(f"place_{ai}_{mi}_{pi}")
                literals.append(literal)
                choices[aid].append((literal, mid, placement))
                if placement.start < placement.finish:
                    for group in activity.get("exclusion_groups", []):
                        workface_intervals.setdefault(group, []).append(model.new_optional_interval_var(
                            placement.start, placement.finish - placement.start, placement.finish, literal,
                            f"workface_{ai}_{mi}_{pi}_{group}"))
                for ri, (requirement, rid) in enumerate(zip(spec.requirements, placement.assignments)):
                    for si, (start, finish) in enumerate(placement.periods):
                        interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                                                                   f"use_{ai}_{mi}_{pi}_{ri}_{si}")
                        if rid is None:
                            raise SchedulingError("internal error: explicit composition deferred a named assignment")
                        named_intervals[rid].append(interval)
            # Empty local availability disables only this mode/method.
            model.add(sum(literals) == mode_var)
        model.add(sum(mode_vars[aid, m["id"]] for m in activity["modes"]) == present)
        model.add(starts[aid] == sum(p.start * lit for lit, _, p in choices[aid]))
        model.add(ends[aid] == sum(p.finish * lit for lit, _, p in choices[aid]))
    for activity in source["activities"]:
        for predecessor in activity.get("predecessors", []):
            model.add(starts[activity["id"]] >= ends[predecessor]).only_enforce_if(presence[activity["id"]])
    by_id = {a["id"]: a for a in source["activities"]}
    packages = {p.id: p for p in problem.work_packages}
    for package in problem.work_packages:
        for method in package.methods:
            ids = set(method.activity_ids)
            roots = [aid for aid in method.activity_ids if not set(by_id[aid].get("predecessors", [])) & ids]
            for predecessor in package.predecessors:
                for prior_method in packages[predecessor].methods:
                    for root in roots:
                        model.add(starts[root] >= ends[prior_method.completion_activity_id]).only_enforce_if(
                            [methods[package.id, method.id], methods[predecessor, prior_method.id]])
    for intervals in named_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    for intervals in workface_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    timing = sum((i + 1) * starts[a["id"]] for i, a in enumerate(source["activities"]))
    stages = [
        _Stage("finish", "finish", ends[source["objective_activity_id"]], environment.horizon),
        _Stage(
            "global_start_timing",
            "global_timing",
            timing,
            environment.horizon * sum(range(1, len(source["activities"]) + 1)),
        ),
    ]
    stages.extend(
        _Stage(
            f"method:{package.id}",
            "method_canonical",
            sum(i * methods[package.id, method.id] for i, method in enumerate(package.methods)),
            len(package.methods) - 1,
        )
        for package in problem.work_packages
    )
    stages.extend(
        _Stage(
            f"mode:{activity['id']}",
            "mode_canonical",
            sum((i + 1) * mode_vars[activity["id"], mode["id"]]
                for i, mode in enumerate(activity["modes"])),
            len(activity["modes"]),
        )
        for activity in source["activities"]
    )
    stages.extend(
        _Stage(
            f"placement:{activity['id']}",
            "placement_canonical",
            sum((i + 1) * literal for i, (literal, _, _) in enumerate(choices[activity["id"]])),
            len(choices[activity["id"]]),
        )
        for activity in source["activities"]
    )
    built = perf_counter()
    return _CompiledWorkMethodTime(
        problem=problem,
        environment=environment,
        specs=specs,
        model=model,
        source=source,
        members=members,
        methods=methods,
        starts=starts,
        ends=ends,
        mode_vars=mode_vars,
        choices=choices,
        stages=tuple(stages),
        placement_count=placement_count,
        workface_interval_count=workface_interval_count,
        started_at=started,
        built_at=built,
        compile_metrics={
            "input_copy_ms": input_copy_ms,
            "validation_ms": validation_ms,
            "productive_case_compile_ms": productive_case_compile_ms,
            "placement_generation_ms": placement_generation_ms,
            "cp_model_assembly_ms": max(
                0.0,
                (built - assembly_started) * 1000 - placement_generation_ms,
            ),
            "base_variables": len(model.proto.variables),
            "base_constraints": len(model.proto.constraints),
        },
    )


def _new_solver() -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = MAX_DETERMINISTIC_TIME_PER_STAGE
    return solver


def _solve_compiled_stages(
    compiled: _CompiledWorkMethodTime,
    stages: tuple[_Stage, ...],
    *,
    solver: cp_model.CpSolver | None = None,
    cumulative_wall_ms: float = 0.0,
    cumulative_deterministic_time: float = 0.0,
):
    """Prove and fix a declared sequence of exact objective stages."""
    if solver is None:
        solver = _new_solver()
    proof = []
    stage_metrics = []
    for stage in stages:
        compiled.model.minimize(stage.expression)
        stage_started = perf_counter()
        status = solver.solve(compiled.model)
        elapsed_ms = (perf_counter() - stage_started) * 1000
        if status == cp_model.INFEASIBLE:
            raise SchedulingError("INFEASIBLE: no executable authorised structure within the declared horizon")
        if status != cp_model.OPTIMAL:
            raise SchedulingError(
                f"{solver.status_name(status)}: {stage.name} is not proven optimal; "
                "no authoritative plan returned"
            )
        value = solver.value(stage.expression)
        proof.append({"stage": stage.name, "value": value, "status": "OPTIMAL"})
        deterministic_time = float(solver.response_proto.deterministic_time)
        cumulative_wall_ms += elapsed_ms
        cumulative_deterministic_time += deterministic_time
        stage_metrics.append({
            "stage": stage.name,
            "stage_type": stage.stage_type,
            "status": "OPTIMAL",
            "value": value,
            "maximum": stage.maximum,
            "elapsed_wall_ms": elapsed_ms,
            "solver_wall_time_ms": float(solver.wall_time) * 1000,
            "deterministic_time": deterministic_time,
            "cumulative_wall_ms": cumulative_wall_ms,
            "cumulative_deterministic_time": cumulative_deterministic_time,
        })
        compiled.model.add(stage.expression == value)
    return solver, proof, stage_metrics


def _solve_sequential(compiled: _CompiledWorkMethodTime):
    """Retained legacy oracle: prove each canonical digit separately."""
    return _solve_compiled_stages(compiled, compiled.stages)


def _canonical_block_stages(
    compiled: _CompiledWorkMethodTime, blocks: tuple[CanonicalBlock, ...],
) -> tuple[_Stage, ...]:
    """Add exact digit witnesses; form block objectives in declared digit order."""
    canonical = {stage.name: stage for stage in compiled.stages[2:]}
    digit_vars = {}
    for digit in (digit for block in blocks for digit in block.digits):
        stage = canonical[digit.name]
        variable = compiled.model.new_int_var(0, digit.maximum, f"canonical_digit_{digit.name}")
        compiled.model.add(variable == stage.expression)
        digit_vars[digit.name] = variable
    result = []
    for block in blocks:
        expression = sum(
            coefficient * digit_vars[digit.name]
            for digit, coefficient in zip(block.digits, block.coefficients)
        )
        result.append(_Stage(block.name, "canonical_block", expression, block.maximum))
    return tuple(result)


def _extract_plan(
    compiled: _CompiledWorkMethodTime,
    solver: cp_model.CpSolver,
    proof: list[dict],
    *,
    compiler: str,
    canonical_blocks: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Extract and independently validate a solved joint candidate."""
    extraction_started = perf_counter()
    problem = compiled.problem
    source = compiled.source
    selected_methods = {
        package.id: next(
            method.id
            for method in package.methods
            if solver.value(compiled.methods[package.id, method.id])
        )
        for package in problem.work_packages
    }
    selected_modes, entries, raw = {}, [], []
    for activity in source["activities"]:
        aid = activity["id"]
        selected = [
            (mid, placement)
            for literal, mid, placement in compiled.choices[aid]
            if solver.value(literal)
        ]
        if not selected:
            continue
        mid, placement = selected[0]
        selected_modes[aid] = mid
        spec = compiled.specs[aid, mid]
        mode = next(m for m in activity["modes"] if m["id"] == mid)
        assignments = tuple((r.id, rid) for r, rid in zip(spec.requirements, placement.assignments))
        raw.append(ra.ScheduledEntry(aid, placement.start, placement.finish, placement.periods, assignments))
        owner = compiled.members.get(aid, (None, None))
        entries.append({"activity_id": aid, "mode_id": mid, "work_package_id": owner[0], "method_id": owner[1],
                        "start": placement.start, "finish": placement.finish,
                        "periods": [list(p) for p in placement.periods],
                        "assignments": [[slot, rid] for slot, rid in assignments if not slot.startswith("@group/")],
                        "group_demands": [[d["group_id"], d["demand"]] for d in mode.get("group_requirements", [])]})
    fixed_case = _case(materialise(problem, selected_methods), selected_modes)
    first_extraction_ms = (perf_counter() - extraction_started) * 1000
    physical_started = perf_counter()
    check = check_allocation(fixed_case, tuple(raw))
    allocation_ms = (perf_counter() - physical_started) * 1000
    if check.status != ra.EXACT_FEASIBLE:
        raise SchedulingError(f"joint result failed independent allocation: {check.reason}")
    plan_started = perf_counter()
    plan = {"schema": PLAN_SCHEMA, "input_hash": input_hash(problem), "policy": POLICY,
            "selected_methods": selected_methods, "selected_modes": selected_modes, "entries": entries,
            "objective": [proof[0]["value"], proof[1]["value"]], "pooled_riggers": False,
            "allocation_witness": [list(row) for row in check.witness if not row[1].startswith("@group/")],
            "physical_status": check.status,
            "solver": {"name": "CP-SAT", "version": ortools.__version__, "workers": 1, "seed": 0,
                       "max_deterministic_time_per_stage": MAX_DETERMINISTIC_TIME_PER_STAGE,
                       "compiler": compiler, "stages": proof,
                       "repeatability": "canonical stage ordering in the same declared environment; not a cross-version guarantee"}}
    if canonical_blocks is not None:
        plan["solver"]["canonical_blocks"] = canonical_blocks
    plan["plan_hash"] = _hash_plan(plan)
    second_extraction_ms = (perf_counter() - plan_started) * 1000
    validation_started = perf_counter()
    validate_plan(problem, plan)
    full_validation_ms = (perf_counter() - validation_started) * 1000
    return plan, {
        "result_extraction_ms": first_extraction_ms + second_extraction_ms,
        "independent_allocation_ms": allocation_ms,
        "stored_plan_validation_ms": full_validation_ms,
        "independent_validation_ms": allocation_ms + full_validation_ms,
    }


def _result_metrics(
    compiled: _CompiledWorkMethodTime,
    stage_metrics: list[dict],
    extraction_metrics: dict,
) -> dict:
    solve_ms = sum(stage["elapsed_wall_ms"] for stage in stage_metrics)
    return {
        "model_builds": 1,
        "solver_calls": len(stage_metrics),
        "placement_alternatives": compiled.placement_count,
        "workface_intervals": compiled.workface_interval_count,
        "variables": len(compiled.model.proto.variables),
        "constraints": len(compiled.model.proto.constraints),
        "build_ms": (compiled.built_at - compiled.started_at) * 1000,
        "solve_ms": solve_ms,
        "end_to_end_ms": (perf_counter() - compiled.started_at) * 1000,
        "stage_metrics": stage_metrics,
        **compiled.compile_metrics,
        **extraction_metrics,
    }


def schedule_work_method_time(problem: WorkMethodTimeProject) -> WorkMethodTimeResult:
    """Calculate the authoritative exact-batched joint structural/productive plan."""
    return _schedule_work_method_time_batched(problem)


def _schedule_work_method_time_batched(
    problem: WorkMethodTimeProject, *, safety_bound: int = MAX_SAFE_BLOCK_VALUE,
    compiler: str = "native-work-method-time-batched/0",
) -> WorkMethodTimeResult:
    """Prove globals separately, then adjacent lower digits in exact safe blocks."""
    compiled = _compile_work_method_time(problem)
    canonical_digits = tuple(
        CanonicalDigit(stage.name, stage.maximum) for stage in compiled.stages[2:]
    )
    blocks = build_lexicographic_blocks(canonical_digits, safety_bound=safety_bound)
    solver, global_proof, global_stage_metrics = _solve_compiled_stages(
        compiled, compiled.stages[:2],
    )
    block_started = perf_counter()
    block_stages = _canonical_block_stages(compiled, blocks)
    block_assembly_ms = (perf_counter() - block_started) * 1000
    solver, block_proof, block_stage_metrics = _solve_compiled_stages(
        compiled, block_stages, solver=solver,
        cumulative_wall_ms=global_stage_metrics[-1]["cumulative_wall_ms"],
        cumulative_deterministic_time=global_stage_metrics[-1]["cumulative_deterministic_time"],
    )
    block_documents = [
        {**block.to_document(), "solved_value": stage["value"]}
        for block, stage in zip(blocks, block_proof)
    ]
    plan, extraction_metrics = _extract_plan(
        compiled, solver, global_proof + block_proof,
        compiler=compiler, canonical_blocks=block_documents,
    )
    metrics = _result_metrics(
        compiled, global_stage_metrics + block_stage_metrics, extraction_metrics,
    )
    metrics.update({
        "canonical_block_assembly_ms": block_assembly_ms,
        "canonical_digits": [
            {"name": digit.name, "maximum": digit.maximum} for digit in canonical_digits
        ],
        "canonical_blocks": block_documents,
        "canonical_block_count": len(blocks),
        "integer_safety_bound": safety_bound,
        "canonical_vector": [
            {
                "name": stage.name, "stage_type": stage.stage_type,
                "value": solver.value(stage.expression), "maximum": stage.maximum,
            }
            for stage in compiled.stages[2:]
        ],
    })
    metrics["end_to_end_ms"] = (perf_counter() - compiled.started_at) * 1000
    return WorkMethodTimeResult(plan, metrics)


def _schedule_work_method_time_sequential_oracle(
    problem: WorkMethodTimeProject,
) -> WorkMethodTimeResult:
    """Test-only historical sequential policy, including original proof identity."""
    compiled = _compile_work_method_time(problem)
    solver, proof, stage_metrics = _solve_sequential(compiled)
    plan, extraction_metrics = _extract_plan(
        compiled,
        solver,
        proof,
        compiler="native-work-method-time/0",
    )
    return WorkMethodTimeResult(
        plan,
        _result_metrics(compiled, stage_metrics, extraction_metrics),
    )
