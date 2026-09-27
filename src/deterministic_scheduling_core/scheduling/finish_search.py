"""Bounded integer feasibility search; one shared finish-proof budget."""
from __future__ import annotations

from hashlib import sha256
from math import ceil, log2
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


def maximum_queries(horizon):
    """Conservative analytic bound: initial + capped doubling + bisection.

    For H>=2, doubling needs at most ceil(log2 H)+1 queries (including
    the horizon cap), followed by at most ceil(log2 H)-1 midpoint queries
    after the last doubling bracket; total <= 1+2*ceil(log2 H).
    H=1 needs at most two queries. The admission bound is H<=480.
    """
    if horizon < 1:
        raise ValueError("positive horizon required")
    return max(2, 1 + 2 * ceil(log2(horizon)))


def exact_bound_search(lower, horizon, query):
    """Return F after SAT at L or after a bracket with F SAT and F-1 UNSAT.

    `query` returns True for closed SAT and False for closed UNSAT. It must
    raise on UNKNOWN. Querying the same bound twice is an invariant failure.
    """
    if lower > horizon:
        raise SchedulingError("INFEASIBLE: no executable authorised structure within the declared horizon")
    if lower < 0 or horizon < 1:
        raise AssertionError("invalid validated finish-search domain")
    seen = set()

    def ask(bound):
        if bound in seen or len(seen) >= maximum_queries(horizon):
            raise AssertionError("finish query-count or duplicate-bound invariant failed")
        seen.add(bound)
        return query(bound)

    if ask(lower):
        return lower
    if lower == horizon:
        raise SchedulingError("INFEASIBLE: no executable authorised structure within the declared horizon")
    unsat, step = lower, 1
    while True:
        upper = min(horizon, lower + step)
        if ask(upper):
            break
        if upper == horizon:
            raise SchedulingError("INFEASIBLE: no executable authorised structure within the declared horizon")
        unsat, step = upper, step * 2
    while unsat + 1 < upper:
        mid = (unsat + upper) // 2
        if ask(mid):
            upper = mid
        else:
            unsat = mid
    # The last SAT upper and immediately adjacent UNSAT lower prove F.
    return upper


def prove_finish(compiled, lower, *, new_solver, budget):
    """Prove exact finish by cloning one unchanged base per bounded SAT query."""
    model = compiled.model
    if model.has_objective():
        raise AssertionError("finish search requires an objective-free base")
    base_digest = sha256(str(model.proto).encode("utf-8")).hexdigest()
    base_vars, base_constraints = len(model.proto.variables), len(model.proto.constraints)
    remaining, rows = float(budget), []
    objective_index = compiled.ends[compiled.source["objective_activity_id"]].index

    def query(bound):
        nonlocal remaining
        if remaining <= 0:
            raise SchedulingError("UNKNOWN: shared finish proof budget exhausted; no authoritative plan returned")
        clone = model.clone()
        end = clone.get_int_var_from_proto_index(objective_index)
        clone.add(end <= bound)
        if len(clone.proto.constraints) != base_constraints + 1:
            raise AssertionError("finish query leaked constraints")
        solver = new_solver()
        solver.parameters.max_deterministic_time = remaining
        started = perf_counter()
        status = solver.solve(clone)
        elapsed_ms = (perf_counter() - started) * 1000
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
            # Fail closed even if a mocked or invalid solver has no response
            # proto. UNKNOWN is neither SAT nor a project infeasibility proof.
            raise SchedulingError(f"{solver.status_name(status)}: finish not proven; no authoritative plan returned")
        used = float(solver.response_proto.deterministic_time)
        if used < 0 or used > remaining + 1e-6:
            raise SchedulingError("UNKNOWN: shared finish proof budget exceeded; no authoritative plan returned")
        remaining = max(0.0, remaining - used)
        sat = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        actual = int(solver.value(end)) if sat else None
        if sat and (actual < lower or actual > bound):
            raise AssertionError("admissible LB1 contradicted by an executable SAT witness")
        rows.append({"bound": bound, "result": "SAT" if sat else "INFEASIBLE",
                     "solver_status": solver.status_name(status), "feasible_finish": actual,
                     "deterministic_time": used, "elapsed_wall_ms": elapsed_ms,
                     "solver_wall_time_ms": float(solver.response_proto.wall_time) * 1000})
        return sat

    finish = exact_bound_search(lower, compiled.environment.horizon, query)
    if (len(model.proto.variables), len(model.proto.constraints)) != (base_vars, base_constraints) or (
            model.has_objective() or sha256(str(model.proto).encode("utf-8")).hexdigest() != base_digest):
        raise AssertionError("finish search mutated its original compiled model")
    return finish, rows, remaining, base_digest
