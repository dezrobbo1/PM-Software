"""Accepted history -> executable remainder semantic contract."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    STATUS_SCHEMA,
    accept_report,
    accept_status_update,
    current_status_records,
    enable_status_tracking,
    load,
    new_blank_workspace,
    new_demo_workspace,
    replace_project,
    report_status_update,
    report_unavailable,
    save,
    state_hash,
    validate,
    validate_accepted_history,
)
from deterministic_scheduling_core.scheduling.planning_workspace import (
    _plan_hash,
    approve,
    propose,
    validate_plan,
    validate_stored_plans,
)
from deterministic_scheduling_core.native_planning_ui.server import BrowserSession, dispatch_action, _comparison
from deterministic_scheduling_core.native_planning_ui.hosted import execute


def _accept(workspace, activity_id, state, **values):
    update_id = report_status_update(
        workspace, activity_id, state, "test-planner", values.pop("reason", "synthetic accepted status"), **values
    )
    accept_status_update(workspace, update_id, "accepting-planner")
    return update_id


def named_statused(*, outage=True, missing=None, remaining=4):
    workspace = new_demo_workspace()
    baseline = propose(workspace)
    approve(workspace, "baseline-planner")
    enable_status_tracking(workspace, 22)
    by_id = {entry["activity_id"]: entry for entry in baseline["entries"]}
    witness = {(activity, slot): resource for activity, slot, resource in baseline["allocation_witness"]}
    states = {
        "A01": "COMPLETED", "A02": "COMPLETED", "A03": "IN_PROGRESS", "A04": "NOT_STARTED",
        "A05": "COMPLETED", "A06": "COMPLETED", "A07": "COMPLETED", "A08": "NOT_STARTED",
    }
    for activity in workspace["project"]["activities"]:
        activity_id = activity["id"]
        if activity_id == missing:
            continue
        state = states[activity_id]
        if state == "NOT_STARTED":
            _accept(workspace, activity_id, state)
            continue
        entry = by_id[activity_id]
        assignments = [[slot, resource if resource is not None else witness[(activity_id, slot)]] for slot, resource in entry["assignments"]]
        values = dict(
            actual_start=entry["start"], actual_finish=entry["finish"], actual_periods=entry["periods"],
            mode_id=baseline["selected_modes"][activity_id], named_assignments=assignments,
            remaining_processing_ticks=0,
        )
        if activity_id == "A03":
            values.update(actual_start=20, actual_finish=None, actual_periods=[[20, 22]],
                          named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]],
                          remaining_processing_ticks=remaining)
        _accept(workspace, activity_id, state, **values)
    if outage:
        report_id = report_unavailable(workspace, "M2", 22, 28, "test-planner", "synthetic accepted outage")
        accept_report(workspace, report_id, "accepting-planner")
    return workspace, baseline


def pooled_statused():
    workspace = new_blank_workspace()
    project = workspace["project"]
    project.update(id="synthetic-pooled-continuation", name="Synthetic pooled continuation", horizon_ticks=240,
                   objective_activity_id="N15", pool_riggers=False)
    project["calendars"] = [
        {"id": "STANDARD", "daily_windows": [[15, 31]]},
        {"id": "RESOURCE_DAY", "daily_windows": [[14, 34]]},
    ]
    project["resources"] = []
    project["resource_groups"] = [
        {"id": group_id, "name": group_id, "capacity": 2, "calendar_id": "RESOURCE_DAY", "disjoint": True, "interchangeable": True}
        for group_id in ("MTP", "ETP")
    ]
    durations = [6, 4, 8, 6, 4, 4, 0, 2, 6, 20, 6, 2, 0, 6, 0]
    predecessors = [[], [], [2], [3], [4], [5], [6], [], [8], [9], [10], [11], [12], [], [1, 7, 13, 14]]
    activities = []
    for number, (duration, prior) in enumerate(zip(durations, predecessors), 1):
        group_id = "ETP" if number in (2, 6, 10) else "MTP"
        demand = 1 if number in (2, 6) else 2
        activities.append({
            "id": f"N{number:02d}", "name": f"Synthetic operation {number}",
            "predecessors": [f"N{value:02d}" for value in prior], "not_before": 0,
            "modes": [{"id": "FIXED", "processing_ticks": duration, "calendar_id": "STANDARD",
                       "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS", "requirements": [],
                       "group_requirements": [{"group_id": group_id, "demand": demand}] if duration else []}],
        })
    project["activities"] = activities
    validate(workspace)
    enable_status_tracking(workspace, 31)
    completed = {
        "N02": (15, 19), "N08": (15, 17), "N09": (17, 23), "N14": (23, 29),
    }
    in_progress = {
        "N03": ([29, 31], 6),
        "N10": ([23, 31], 16),
    }
    for activity in activities:
        activity_id = activity["id"]
        if activity_id in completed:
            start, finish = completed[activity_id]
            _accept(workspace, activity_id, "COMPLETED", actual_start=start, actual_finish=finish,
                    actual_periods=[[start, finish]], mode_id="FIXED", named_assignments=[], remaining_processing_ticks=0)
        elif activity_id in in_progress:
            period, remaining = in_progress[activity_id]
            _accept(workspace, activity_id, "IN_PROGRESS", actual_start=period[0], actual_finish=None,
                    actual_periods=[period], mode_id="FIXED", named_assignments=[], remaining_processing_ticks=remaining)
        else:
            _accept(workspace, activity_id, "NOT_STARTED")
    return workspace


class AcceptedExecutionHistoryTests(unittest.TestCase):
    def history_case(self, continuity="SUSPENDABLE_AT_AVAILABILITY_GAPS", grouped=False):
        workspace = new_blank_workspace()
        project = workspace["project"]
        project.update(horizon_ticks=48, objective_activity_id="H", pool_riggers=False, resources=[])
        project["calendars"] = [{"id": "ALL", "daily_windows": [[0, 48]]}]
        project["resource_groups"] = ([{"id": "G", "name": "G", "capacity": 2,
            "calendar_id": "ALL", "disjoint": True, "interchangeable": True}] if grouped else [])
        project["activities"] = [{"id": aid, "name": aid, "not_before": 0,
            "predecessors": ["X"] if aid == "H" else [], "modes": [{"id": "USED",
            "processing_ticks": 0 if aid == "H" else 2, "calendar_id": "ALL",
            "continuity": continuity, "requirements": [],
            "group_requirements": [{"group_id": "G", "demand": 1}] if grouped and aid != "H" else []}]}
            for aid in ("X", "H")]
        enable_status_tracking(workspace, 26)
        _accept(workspace, "H", "NOT_STARTED")
        return workspace

    def test_suspendable_in_progress_checks_eligible_time_through_status(self):
        for periods in ([[20, 22]], []):
            with self.subTest(periods=periods):
                workspace = self.history_case()
                update = report_status_update(workspace, "X", "IN_PROGRESS", "planner", "trailing gap",
                    actual_start=20, actual_periods=periods, mode_id="USED", remaining_processing_ticks=2)
                before = deepcopy(workspace)
                with self.assertRaisesRegex(ValueError, "suspension gap"):
                    accept_status_update(workspace, update, "planner")
                self.assertEqual(workspace, before)
                invalid = deepcopy(workspace)
                invalid["execution"]["updates"][-1].update(status="ACCEPTED", accepted_by="planner", accepted_at="test")
                with self.assertRaisesRegex(ValueError, "suspension gap"):
                    validate(invalid)
        for periods, start, remaining, windows in (
            ([[20, 22]], 20, 2, [[20, 22], [26, 30]]),
            ([], 20, 2, [[26, 30]]),
            ([], 26, 2, [[0, 48]]),
            ([[20, 22]], 20, 0, [[0, 48]]),
        ):
            with self.subTest(periods=periods, remaining=remaining, windows=windows):
                workspace = self.history_case()
                workspace["project"]["calendars"][0]["daily_windows"] = windows
                _accept(workspace, "X", "IN_PROGRESS", actual_start=start, actual_periods=periods,
                    mode_id="USED", remaining_processing_ticks=remaining)
                plan = propose(workspace)
                validate_plan(workspace, plan)
                self.assertEqual(current_status_records(workspace)["X"]["execution_state"], "IN_PROGRESS")

    def named_history_case(self):
        workspace = self.history_case()
        workspace["project"]["resources"] = [{"id": rid, "capabilities": ["Q"], "calendar_id": "ALL", "capacity": 1}
            for rid in ("R1", "R2")]
        workspace["project"]["activities"][0]["modes"][0]["requirements"] = [
            {"id": slot, "pool_ids": ["Q"], "eligible_resource_ids": [rid]}
            for slot, rid in (("ONE", "R1"), ("TWO", "R2"))]
        return workspace

    def test_assignment_row_order_preserves_historical_context_on_correction(self):
        workspace = self.named_history_case()
        pairs = [["ONE", "R1"], ["TWO", "R2"]]
        prior_id = _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=26,
            actual_periods=[[20, 26]], mode_id="USED", named_assignments=pairs, remaining_processing_ticks=0)
        prior = deepcopy(current_status_records(workspace)["X"])
        propose(workspace); approve(workspace, "planner")
        outage = report_unavailable(workspace, "R2", 22, 24, "planner", "later availability")
        accept_report(workspace, outage, "planner")
        for ordered in (pairs, pairs[::-1]):
            with self.subTest(assignments=ordered):
                candidate = deepcopy(workspace)
                update = report_status_update(candidate, "X", "COMPLETED", "planner", "invalid gap correction",
                    actual_start=20, actual_finish=26, actual_periods=[[20, 22], [24, 26]], mode_id="USED",
                    named_assignments=ordered, remaining_processing_ticks=0, supersedes_update_id=prior_id)
                before = deepcopy(candidate)
                with self.assertRaisesRegex(ValueError, "suspension gap"):
                    accept_status_update(candidate, update, "planner")
                self.assertEqual(candidate, before)
        _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=26, actual_periods=[[20, 26]],
            mode_id="USED", named_assignments=pairs[::-1], remaining_processing_ticks=0, supersedes_update_id=prior_id)
        self.assertEqual(current_status_records(workspace)["X"]["execution_context"], prior["execution_context"])
        self.assertIn(prior, workspace["execution"]["updates"])
        validate_plan(workspace, propose(workspace)); approve(workspace, "planner")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "reordered.json"; save(workspace, path)
            self.assertEqual(load(path), workspace)

    def test_import_rejects_outage_for_unassigned_historical_resource(self):
        workspace = self.named_history_case()
        workspace["project"]["activities"][0]["modes"][0]["requirements"].pop()
        _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=26, actual_periods=[[20, 26]],
            mode_id="USED", named_assignments=[["ONE", "R1"]], remaining_processing_ticks=0)
        outage = report_unavailable(workspace, "R2", 22, 24, "planner", "unrelated availability")
        accept_report(workspace, outage, "planner")
        invalid = deepcopy(workspace)
        record = current_status_records(invalid)["X"]
        record["actual_periods"] = [[20, 22], [24, 26]]
        record["execution_context"]["named_resources"].append(deepcopy(workspace["project"]["resources"][1]))
        record["execution_context"]["accepted_outages"] = [deepcopy(next(r for r in workspace["reports"] if r["id"] == outage))]
        with self.assertRaisesRegex(ValueError, "historical.*(outage|resource)"):
            validate(invalid)
        session = BrowserSession(); before = deepcopy(session.workspace)
        with self.assertRaises(ValueError): dispatch_action("/api/open", {"workspace": invalid}, session)
        self.assertEqual(session.workspace, before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"; path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError): load(path)

    def test_merged_v2_snapshot_reopens_without_normalizing_or_rehashing(self):
        fixture = Path(__file__).parent / "fixtures/accepted-history/merged-v2-metadata-duplicates.json"
        original = fixture.read_bytes()
        self.assertEqual(sha256(original).hexdigest(), "3cd832702e114ad01d5a64ecd793623490d5f0ff8721c3e1b77ff9c37a519d4f")
        workspace = load(fixture)
        self.assertEqual(workspace, json.loads(original))
        self.assertEqual(state_hash(workspace), "96cdd690d9f09e83a909f4c6f9fe2b6196d34970e6b081db147636b923bee8cb")
        self.assertEqual(workspace["approved_plan"]["plan_hash"], "e41133340a29f8fa3273dded833e53ea904eabf905bc45a218340fd219e1f828")
        before = deepcopy(workspace)
        validate_stored_plans(workspace)
        session = BrowserSession(); dispatch_action("/api/open", {"workspace": workspace}, session)
        self.assertEqual(session.workspace, before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "reopened.json"; save(workspace, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(load(path), before)
        self.assertEqual(workspace, before)
        validate_plan(workspace, propose(workspace))
        self.assertEqual(workspace["execution"], before["execution"])

    def test_accepted_project_metadata_and_duplicate_qualifications_allow_progress(self):
        for kind in ("calendar", "capabilities", "qualifications"):
            with self.subTest(kind=kind):
                workspace = self.named_history_case()
                project = deepcopy(workspace["project"])
                if kind == "calendar": project["calendars"][0]["name"] = "Legacy display metadata"
                if kind == "capabilities": project["resources"][0]["capabilities"] = ["Q", "Q"]
                if kind == "qualifications": project["activities"][0]["modes"][0]["requirements"][0]["pool_ids"] = ["Q", "Q"]
                replace_project(workspace, project)
                _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=26, actual_periods=[[20, 26]],
                    mode_id="USED", named_assignments=[["ONE", "R1"], ["TWO", "R2"]], remaining_processing_ticks=0)
                self.assertEqual(workspace["project"], project)
                context = current_status_records(workspace)["X"]["execution_context"]
                self.assertEqual(context["calendars"], project["calendars"])
                self.assertEqual(context["named_resources"], project["resources"])
                self.assertEqual(context["mode"], project["activities"][0]["modes"][0])
                validate_plan(workspace, propose(workspace))

    def test_v2_named_capacity_one_preserves_representation_through_progress(self):
        for capacity in (True, 1.0, 1, "omitted"):
            with self.subTest(capacity=capacity):
                workspace = self.named_history_case()
                project = deepcopy(workspace["project"])
                if capacity == "omitted":
                    project["resources"][0].pop("capacity")
                else:
                    project["resources"][0]["capacity"] = capacity
                replace_project(workspace, project)
                values = dict(actual_start=20, actual_periods=[[20, 26]], mode_id="USED",
                    named_assignments=[["ONE", "R1"], ["TWO", "R2"]], remaining_processing_ticks=2)
                old_id = _accept(workspace, "X", "IN_PROGRESS", **values)
                _accept(workspace, "X", "IN_PROGRESS", supersedes_update_id=old_id, **values)
                for record in workspace["execution"]["updates"]:
                    if record["activity_id"] == "X":
                        self.assertEqual(json.dumps(record["execution_context"]["named_resources"]),
                                         json.dumps(project["resources"]))
                validate_plan(workspace, propose(workspace))
                before = json.dumps(workspace, sort_keys=True)
                original_hash = state_hash(workspace)
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "capacity.json"
                    save(workspace, path)
                    original_bytes = path.read_bytes()
                    reopened = load(path)
                    self.assertEqual(json.dumps(reopened, sort_keys=True), before)
                    self.assertEqual(state_hash(reopened), original_hash)
                    save(reopened, path)
                    self.assertEqual(path.read_bytes(), original_bytes)

    def test_v2_string_capabilities_preserve_history_and_set_semantics(self):
        for capabilities in ("Q", "QQ", "QR", ["Q"], ["Q", "Q"]):
            with self.subTest(capabilities=capabilities):
                workspace = self.named_history_case()
                project = deepcopy(workspace["project"])
                project["resources"][0]["capabilities"] = capabilities
                replace_project(workspace, project)
                values = dict(actual_start=20, actual_periods=[[20, 26]], mode_id="USED",
                    named_assignments=[["ONE", "R1"], ["TWO", "R2"]], remaining_processing_ticks=2)
                old_id = _accept(workspace, "X", "IN_PROGRESS", **values)
                _accept(workspace, "X", "IN_PROGRESS", supersedes_update_id=old_id, **values)
                for record in workspace["execution"]["updates"]:
                    if record["activity_id"] == "X":
                        self.assertEqual(record["execution_context"]["named_resources"][0]["capabilities"], capabilities)
                validate_plan(workspace, propose(workspace))
                before = deepcopy(workspace)
                original_hash = state_hash(workspace)
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "capabilities.json"
                    save(workspace, path)
                    original_bytes = path.read_bytes()
                    reopened = load(path)
                    self.assertEqual(reopened, before)
                    self.assertEqual(state_hash(reopened), original_hash)
                    save(reopened, path)
                    self.assertEqual(path.read_bytes(), original_bytes)
                # A scalar string retains legacy character-set semantics; it
                # must not become one new multi-character qualification.
                invalid = deepcopy(workspace)
                current_status_records(invalid)["X"]["execution_context"]["mode"]["requirements"][0]["pool_ids"] = ["QR"]
                with self.assertRaises(ValueError):
                    validate(invalid)

    def test_v2_string_qualifications_preserve_captured_modes(self):
        for pools in ("Q", "QQ", "QR"):
            with self.subTest(pools=pools):
                workspace = self.named_history_case()
                project = deepcopy(workspace["project"])
                project["resources"][0]["capabilities"] = ["Q", "R"]
                project["activities"][0]["modes"][0]["requirements"][0]["pool_ids"] = pools
                replace_project(workspace, project)
                values = dict(actual_start=20, actual_periods=[[20, 26]], mode_id="USED",
                    named_assignments=[["ONE", "R1"], ["TWO", "R2"]], remaining_processing_ticks=2)
                old_id = _accept(workspace, "X", "IN_PROGRESS", **values)
                _accept(workspace, "X", "IN_PROGRESS", supersedes_update_id=old_id, **values)
                for record in workspace["execution"]["updates"]:
                    if record["activity_id"] == "X":
                        self.assertEqual(record["execution_context"]["mode"]["requirements"][0]["pool_ids"], pools)
                validate_plan(workspace, propose(workspace))
                original_hash = state_hash(workspace)
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "qualifications.json"
                    save(workspace, path)
                    original_bytes = path.read_bytes()
                    reopened = load(path)
                    self.assertEqual(reopened, workspace)
                    self.assertEqual(state_hash(reopened), original_hash)
                    save(reopened, path)
                    self.assertEqual(path.read_bytes(), original_bytes)

    def test_superseded_accepted_context_structure_is_validated(self):
        workspace = self.named_history_case()
        values = dict(actual_start=20, actual_finish=26, actual_periods=[[20, 26]], mode_id="USED",
            named_assignments=[["ONE", "R1"], ["TWO", "R2"]], remaining_processing_ticks=0)
        old_id = _accept(workspace, "X", "COMPLETED", **values)
        _accept(workspace, "X", "COMPLETED", supersedes_update_id=old_id, **values)
        for kind in ("processing", "calendar", "resource", "outage"):
            with self.subTest(kind=kind):
                invalid = deepcopy(workspace)
                context = next(u for u in invalid["execution"]["updates"] if u["id"] == old_id)["execution_context"]
                if kind == "processing": context["mode"]["processing_ticks"] = -1
                if kind == "calendar": context["calendars"][0]["daily_windows"] = [[22, 20]]
                if kind == "resource": context["named_resources"][0]["capacity"] = 2
                if kind == "outage": context["accepted_outages"] = [{"status": "ACCEPTED", "resource_id": "R1", "accepted_by": "planner", "start": 22, "finish": 20}]
                with self.assertRaises(ValueError): validate(invalid)
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "invalid.json"; path.write_text(json.dumps(invalid))
                    with self.assertRaises(ValueError): load(path)

    def test_corrected_factual_history_is_retained_but_not_current_feasibility(self):
        workspace, _ = named_statused()
        old = deepcopy(current_status_records(workspace)["A01"])
        _accept(workspace, "A01", "COMPLETED", actual_start=14, actual_finish=16, actual_periods=[[14, 16]],
            mode_id="FIXED", remaining_processing_ticks=0, supersedes_update_id=old["id"])
        # Imported correction: the original assertion was factually wrong,
        # outside its historical calendar, but its captured structure is valid.
        prior = next(u for u in workspace["execution"]["updates"] if u["id"] == old["id"])
        prior.update(actual_start=0, actual_finish=2, actual_periods=[[0, 2]])
        before = deepcopy(workspace["execution"])
        validate(workspace); validate_plan(workspace, propose(workspace))
        self.assertEqual(workspace["execution"], before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "corrected.json"; save(workspace, path)
            self.assertEqual(load(path), workspace)
        invalid = deepcopy(workspace)
        invalid["execution"]["updates"].pop()  # The erroneous assertion is current again.
        with self.assertRaisesRegex(ValueError, "historical activity calendar"):
            validate(invalid)

    def test_import_rejects_malformed_captured_native_context(self):
        named = self.named_history_case()
        _accept(named, "X", "COMPLETED", actual_start=20, actual_finish=26,
                actual_periods=[[20, 26]], mode_id="USED",
                named_assignments=[["ONE", "R1"], ["TWO", "R2"]],
                remaining_processing_ticks=0)
        grouped = self.history_case(grouped=True)
        _accept(grouped, "X", "COMPLETED", actual_start=20, actual_finish=26,
                actual_periods=[[20, 26]], mode_id="USED",
                named_assignments=[], remaining_processing_ticks=0)

        def current(workspace):
            return current_status_records(workspace)["X"]["execution_context"]

        corruptions = [
            ("negative processing", named, lambda ctx: (
                ctx["mode"].__setitem__("processing_ticks", -1),
                current_status_records(invalid)["X"].__setitem__("actual_periods", []),
            )),
            ("bad continuity", named, lambda ctx: ctx["mode"].__setitem__("continuity", "ARBITRARY")),
            ("bad calendar", named, lambda ctx: ctx["calendars"][0].__setitem__("daily_windows", [[20, 20]])),
            ("bad named capacity", named, lambda ctx: ctx["named_resources"][0].__setitem__("capacity", 2)),
            ("bad named capacity type", named, lambda ctx: ctx["named_resources"][0].__setitem__("capacity", "1")),
            ("bad group capacity", grouped, lambda ctx: ctx["resource_groups"][0].__setitem__("capacity", 0)),
            ("oversized group capacity", grouped, lambda ctx: ctx["resource_groups"][0].__setitem__("capacity", 33)),
        ]
        for label, source, corrupt in corruptions:
            with self.subTest(label=label):
                invalid = deepcopy(source)
                corrupt(current(invalid))
                with self.assertRaises(ValueError):
                    validate(invalid)

        invalid = deepcopy(named)
        current(invalid)["mode"]["processing_ticks"] = -1
        current_status_records(invalid)["X"]["actual_periods"] = []
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-captured-context.json"
            path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                load(path)
        session = BrowserSession()
        before = deepcopy(session.workspace)
        with self.assertRaises(ValueError):
            dispatch_action("/api/open", {"workspace": invalid}, session)
        self.assertEqual(session.workspace, before)

    def test_continuous_in_progress_must_reach_status_boundary(self):
        for periods in ([[20, 22]], []):
            with self.subTest(periods=periods):
                workspace = self.history_case("CONTINUOUS")
                update = report_status_update(workspace, "X", "IN_PROGRESS", "planner", "incomplete history",
                    actual_start=20, actual_periods=periods, mode_id="USED", remaining_processing_ticks=2)
                before = deepcopy(workspace)
                with self.assertRaisesRegex(ValueError, "continuous.*status"):
                    accept_status_update(workspace, update, "planner")
                self.assertEqual(workspace, before)

    def test_continuous_status_boundary_allows_immediate_start_and_explicit_zero(self):
        for start, periods, remaining in ((26, [], 2), (20, [[20, 26]], 2), (20, [[20, 26]], 0)):
            with self.subTest(start=start, remaining=remaining):
                workspace = self.history_case("CONTINUOUS")
                _accept(workspace, "X", "IN_PROGRESS", actual_start=start, actual_periods=periods,
                    mode_id="USED", remaining_processing_ticks=remaining)
                plan = propose(workspace); validate_plan(workspace, plan)
                entry = next(e for e in plan["entries"] if e["activity_id"] == "X")
                self.assertEqual(entry["execution_state"], "IN_PROGRESS")
                self.assertEqual(entry["forecast_periods"], [[26, 28]] if remaining else [])
                self.assertEqual(entry["actual_periods"], periods)

    def test_completed_productive_work_requires_recorded_periods(self):
        for continuity in ("CONTINUOUS", "SUSPENDABLE_AT_AVAILABILITY_GAPS", None):
            for finish in (20, 22):
                with self.subTest(continuity=continuity, finish=finish):
                    workspace = self.history_case(continuity or "SUSPENDABLE_AT_AVAILABILITY_GAPS")
                    if continuity is None:
                        del workspace["project"]["activities"][0]["modes"][0]["continuity"]
                    update = report_status_update(workspace, "X", "COMPLETED", "planner", "missing actual work",
                        actual_start=20, actual_finish=finish, actual_periods=[], mode_id="USED", remaining_processing_ticks=0)
                    before = deepcopy(workspace)
                    with self.assertRaisesRegex(ValueError, "completed.*productive.*period"):
                        accept_status_update(workspace, update, "planner")
                    self.assertEqual(workspace, before)

    def test_continuous_start_at_status_cannot_be_delayed_into_a_later_window(self):
        workspace = self.history_case("CONTINUOUS")
        _accept(workspace, "X", "IN_PROGRESS", actual_start=26, actual_periods=[],
            mode_id="USED", remaining_processing_ticks=2)
        plan = propose(workspace)
        corrupted = deepcopy(plan)
        entry = next(e for e in corrupted["entries"] if e["activity_id"] == "X")
        entry.update(start=30, finish=32, periods=[[30, 32]], forecast_start=30,
            forecast_finish=32, forecast_periods=[[30, 32]])
        handoff = next(e for e in corrupted["entries"] if e["activity_id"] == "H")
        handoff.update(start=32, finish=32, forecast_start=32, forecast_finish=32)
        corrupted["project_finish"] = 32
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "continuous.*gap"):
            validate_plan(workspace, corrupted)
        changed = deepcopy(workspace["project"])
        changed["calendars"][0]["daily_windows"] = [[30, 40]]
        replace_project(workspace, changed)
        with self.assertRaisesRegex(SchedulingError, "no executable future"):
            propose(workspace)

    def test_retired_in_progress_mode_can_be_confirmed_completed(self):
        workspace, _ = named_statused()
        prior = deepcopy(current_status_records(workspace)["A03"])
        project = deepcopy(workspace["project"])
        activity = next(a for a in project["activities"] if a["id"] == "A03")
        activity["modes"] = [m for m in activity["modes"] if m["id"] != "SPECIALIST"]
        replace_project(workspace, project)
        with self.assertRaisesRegex(ValueError, "no longer authorised"):
            propose(workspace)
        _accept(workspace, "A03", "COMPLETED", actual_start=20, actual_finish=22,
            actual_periods=[[20, 22]], mode_id="SPECIALIST", named_assignments=prior["named_assignments"],
            remaining_processing_ticks=0, supersedes_update_id=prior["id"])
        current = current_status_records(workspace)["A03"]
        self.assertEqual(current["execution_context"], prior["execution_context"])
        self.assertIn(prior, workspace["execution"]["updates"])
        plan = propose(workspace); validate_plan(workspace, plan)
        entry = next(e for e in plan["entries"] if e["activity_id"] == "A03")
        self.assertEqual(entry["forecast_periods"], [])
        self.assertEqual(plan["selected_modes"]["A03"], "SPECIALIST")
        approve(workspace, "test-only")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "completion.json"; save(workspace, path)
            reopened = load(path); validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)

    def test_empty_history_cannot_assign_one_person_to_two_slots(self):
        workspace = self.history_case()
        workspace["project"]["resources"] = [{"id": rid, "capabilities": ["Q"], "calendar_id": "ALL", "capacity": 1}
            for rid in ("R1", "R2")]
        workspace["project"]["activities"][0]["modes"][0]["requirements"] = [
            {"id": slot, "pool_ids": ["Q"], "eligible_resource_ids": ["R1", "R2"]} for slot in ("ONE", "TWO")]
        update = report_status_update(workspace, "X", "IN_PROGRESS", "planner", "duplicate person",
            actual_start=26, actual_periods=[], mode_id="USED", remaining_processing_ticks=2,
            named_assignments=[["ONE", "R1"], ["TWO", "R1"]])
        before = deepcopy(workspace)
        with self.assertRaisesRegex(ValueError, "distinct.*named"):
            accept_status_update(workspace, update, "planner")
        self.assertEqual(workspace, before)
        _accept(workspace, "X", "IN_PROGRESS", actual_start=26, actual_periods=[], mode_id="USED",
            remaining_processing_ticks=2, named_assignments=[["ONE", "R1"], ["TWO", "R2"]])
        validate_plan(workspace, propose(workspace))

    def test_import_checks_current_history_without_requiring_all_statuses(self):
        workspace = new_demo_workspace(); enable_status_tracking(workspace, 22)
        _accept(workspace, "A01", "COMPLETED", actual_start=14, actual_finish=16,
            actual_periods=[[14, 16]], mode_id="FIXED", remaining_processing_ticks=0)
        # Missing statuses remain UNKNOWN, but a valid partial workspace opens.
        session = BrowserSession()
        dispatch_action("/api/open", {"workspace": workspace}, session)
        self.assertEqual(session.workspace, workspace)
        corruptions = []
        outside = deepcopy(workspace)
        outside["execution"]["updates"][0].update(actual_start=0, actual_finish=2, actual_periods=[[0, 2]])
        corruptions.append(outside)
        named, _ = named_statused(outage=False)
        named["approved_plan"] = named["proposal"] = None
        current_status_records(named)["A06"]["named_assignments"] = [["RIGGER", "R1"]]
        current_status_records(named)["A06"]["execution_context"] = deepcopy(current_status_records(named)["A05"]["execution_context"])
        current_status_records(named)["A06"]["execution_context"]["activity_id"] = "A06"
        corruptions.append(named)
        grouped = pooled_statused()
        record = current_status_records(grouped)["N10"]
        record.update(actual_start=17, actual_periods=[[17, 25]])
        corruptions.append(grouped)
        with TemporaryDirectory() as directory:
            for index, invalid in enumerate(corruptions):
                with self.subTest(index=index):
                    before = deepcopy(session.workspace)
                    with self.assertRaises(ValueError):
                        dispatch_action("/api/open", {"workspace": invalid}, session)
                    self.assertEqual(session.workspace, before)
                    path = Path(directory) / "invalid.json"; path.write_text(json.dumps(invalid))
                    with self.assertRaises(ValueError): load(path)
                    with self.assertRaises(ValueError): validate(invalid)

    def test_continuous_history_requires_complete_actual_envelope_atomically(self):
        for start, finish, periods in ((20, 24, [[22, 24]]), (22, 26, [[22, 24]]),
                                       (20, 26, []), (20, 24, [[20, 21], [23, 24]])):
            with self.subTest(start=start, finish=finish, periods=periods):
                workspace = self.history_case("CONTINUOUS")
                update = report_status_update(workspace, "X", "COMPLETED", "planner", "review actual",
                    actual_start=start, actual_finish=finish, actual_periods=periods,
                    mode_id="USED", remaining_processing_ticks=0)
                before = deepcopy(workspace)
                with self.assertRaisesRegex(ValueError, "continuous|CONTINUOUS"):
                    accept_status_update(workspace, update, "planner")
                self.assertEqual(workspace, before)
                # A manually re-labelled accepted record must not bypass the
                # independent historical check either.
                record = workspace["execution"]["updates"][-1]
                record.update(status="ACCEPTED", accepted_by="planner", accepted_at="test")
                with self.assertRaisesRegex(ValueError, "continuous|CONTINUOUS"):
                    validate_accepted_history(workspace, require_complete=True)

    def test_continuous_adjacent_periods_and_explicit_milestone_are_valid(self):
        workspace = self.history_case("CONTINUOUS")
        _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=24,
                actual_periods=[[20, 22], [22, 24]], mode_id="USED", remaining_processing_ticks=0)
        self.assertEqual(propose(workspace)["project_finish"], 26)
        workspace = self.history_case("CONTINUOUS")
        workspace["project"]["activities"][0]["modes"][0]["processing_ticks"] = 0
        _accept(workspace, "X", "COMPLETED", actual_start=20, actual_finish=20,
                actual_periods=[], mode_id="USED", remaining_processing_ticks=0)
        validate_plan(workspace, propose(workspace))

    def test_suspendable_history_rejects_arbitrary_or_leading_eligible_gaps(self):
        for periods in ([[10, 11], [20, 21]], [[20, 21]]):
            workspace = self.history_case()
            update = report_status_update(workspace, "X", "COMPLETED", "planner", "review actual",
                actual_start=10, actual_finish=21, actual_periods=periods,
                mode_id="USED", remaining_processing_ticks=0)
            before = deepcopy(workspace)
            with self.assertRaisesRegex(ValueError, "gap|suspension"):
                accept_status_update(workspace, update, "planner")
            self.assertEqual(workspace, before)

    def test_historical_group_allocation_rejects_triangle_before_acceptance(self):
        workspace = self.history_case(grouped=True)
        template = workspace["project"]["activities"][0]
        periods = {"X": [[0, 1], [2, 3]], "Y": [[0, 1], [4, 5]], "Z": [[2, 3], [4, 5]]}
        project = deepcopy(workspace["project"])
        project["activities"] = []
        for aid, actual in periods.items():
            activity = deepcopy(template); activity.update(id=aid, name=aid)
            activity["modes"][0]["calendar_id"] = aid
            project["calendars"].append({"id": aid, "daily_windows": actual})
            project["activities"].append(activity)
        handoff = deepcopy(workspace["project"]["activities"][-1]); handoff["predecessors"] = list(periods)
        project["activities"].append(handoff); replace_project(workspace, project)
        for aid in ("X", "Y"):
            actual = periods[aid]
            _accept(workspace, aid, "COMPLETED", actual_start=actual[0][0], actual_finish=actual[-1][1],
                    actual_periods=actual, mode_id="USED", remaining_processing_ticks=0)
        update = report_status_update(workspace, "Z", "COMPLETED", "planner", "third conflict",
            actual_start=2, actual_finish=5, actual_periods=periods["Z"], mode_id="USED", remaining_processing_ticks=0)
        before = deepcopy(workspace)
        with self.assertRaisesRegex(ValueError, "accepted.*group.*no-handover"):
            accept_status_update(workspace, update, "planner")
        self.assertEqual(workspace, before)
        record = workspace["execution"]["updates"][-1]
        record.update(status="ACCEPTED", accepted_by="planner", accepted_at="test")
        with self.assertRaisesRegex(ValueError, "accepted.*group.*no-handover"):
            propose(workspace)

    def test_historical_joint_calendar_gap_and_outage_context_remain_fixed(self):
        for gap_source in ("activity", "group", "named", "outage"):
            with self.subTest(gap_source=gap_source):
                workspace = self.history_case(grouped=gap_source == "group")
                project = workspace["project"]
                project["calendars"].append({"id": "GAP", "daily_windows": [[10, 11], [20, 21]]})
                mode = project["activities"][0]["modes"][0]
                assignments = []
                if gap_source == "activity": mode["calendar_id"] = "GAP"
                if gap_source == "group": project["resource_groups"][0]["calendar_id"] = "GAP"
                if gap_source in ("named", "outage"):
                    project["resources"] = [{"id": "R", "capabilities": ["Q"],
                        "calendar_id": "GAP" if gap_source == "named" else "ALL", "capacity": 1}]
                    mode["requirements"] = [{"id": "S", "pool_ids": ["Q"], "eligible_resource_ids": ["R"]}]
                    assignments = [["S", "R"]]
                if gap_source == "outage":
                    outage = report_unavailable(workspace, "R", 11, 20, "planner", "historical outage")
                    accept_report(workspace, outage, "planner")
                _accept(workspace, "X", "COMPLETED", actual_start=10, actual_finish=21,
                    actual_periods=[[10, 11], [20, 21]], mode_id="USED", named_assignments=assignments,
                    remaining_processing_ticks=0)
                accepted = deepcopy(current_status_records(workspace)["X"])
                if gap_source == "outage":
                    self.assertEqual(accepted["execution_context"]["accepted_outages"][0]["id"], outage)
                    later = report_unavailable(workspace, "R", 10, 11, "planner", "later future input")
                    accept_report(workspace, later, "planner")
                changed = deepcopy(project)
                changed["calendars"] = [{"id": c["id"], "daily_windows": [[30, 40]]} for c in project["calendars"]]
                replace_project(workspace, changed)
                validate_accepted_history(workspace, require_complete=True)
                self.assertEqual(current_status_records(workspace)["X"], accepted)
                validate_plan(workspace, propose(workspace))

    def test_completed_retired_mode_recovery_correction_and_reopen(self):
        workspace, _ = named_statused()
        prior = deepcopy(current_status_records(workspace)["A01"])
        project = deepcopy(workspace["project"])
        next(a for a in project["activities"] if a["id"] == "A01")["modes"][0]["id"] = "REPLACEMENT"
        replace_project(workspace, project)
        plan = propose(workspace)
        self.assertEqual(plan["selected_modes"]["A01"], "FIXED")
        self.assertEqual(next(e for e in plan["entries"] if e["activity_id"] == "A01")["actual_periods"], [[14, 16]])
        validate_plan(workspace, plan)
        approve(workspace, "test-only")
        _accept(workspace, "A01", "COMPLETED", actual_start=14, actual_finish=16,
                actual_periods=[[14, 16]], mode_id="FIXED", remaining_processing_ticks=0,
                supersedes_update_id=prior["id"])
        self.assertEqual(current_status_records(workspace)["A01"]["execution_context"], prior["execution_context"])
        propose(workspace)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "retired-mode.json"; save(workspace, path)
            reopened = load(path); validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)

    def test_in_progress_retired_mode_is_still_not_executable(self):
        workspace, _ = named_statused()
        project = deepcopy(workspace["project"])
        activity = next(a for a in project["activities"] if a["id"] == "A03")
        activity["modes"] = [m for m in activity["modes"] if m["id"] != "SPECIALIST"]
        replace_project(workspace, project)
        with self.assertRaisesRegex(ValueError, "no longer authorised"):
            propose(workspace)

    def test_comparison_does_not_invent_changes_for_completed_history(self):
        workspace, _ = named_statused()
        propose(workspace)
        comparison = _comparison(workspace)
        completed = {"A01", "A02", "A05", "A06", "A07"}
        self.assertTrue(completed <= set(comparison["unchanged_activity_ids"]))
        for field in ("changed_periods", "changed_assignments", "changed_group_demands"):
            self.assertFalse(completed & {e["activity_id"] for e in comparison[field]})

    def test_comparison_detects_actual_correction_when_forecast_is_unchanged(self):
        workspace, _ = named_statused()
        propose(workspace); approve(workspace, "test-only")
        prior = current_status_records(workspace)["A03"]
        _accept(workspace, "A03", "IN_PROGRESS", actual_start=21, actual_periods=[[21, 22]],
                mode_id="SPECIALIST", named_assignments=prior["named_assignments"],
                remaining_processing_ticks=4, supersedes_update_id=prior["id"])
        propose(workspace)
        comparison = _comparison(workspace)
        self.assertNotIn("A03", comparison["unchanged_activity_ids"])
        change = next(e for e in comparison["changed_periods"] if e["activity_id"] == "A03")
        self.assertEqual(change["old"], [[20, 22], [28, 32]])
        self.assertEqual(change["new"], [[21, 22], [28, 32]])

    def test_legacy_profiles_reject_mixed_execution_fields(self):
        for workspace in (new_demo_workspace(), new_blank_workspace()):
            workspace["execution"] = {"status_point": 22, "updates": []}
            with self.assertRaisesRegex(ValueError, "version two|version-two"):
                validate(workspace)

    def test_supersession_cycles_and_forks_are_rejected_on_open(self):
        workspace, _ = named_statused(outage=False)
        original = current_status_records(workspace)["A03"]
        correction = deepcopy(original)
        correction.update(id="U009", supersedes_update_id=original["id"])
        workspace["execution"]["updates"].append(correction)
        original["supersedes_update_id"] = correction["id"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate(workspace)
        original["supersedes_update_id"] = None
        fork = deepcopy(correction)
        fork["id"] = "U010"
        workspace["execution"]["updates"].append(fork)
        with self.assertRaisesRegex(ValueError, "competing|fork"):
            validate(workspace)

    def test_estimate_correction_retains_history_after_future_calendar_edit(self):
        workspace, _ = named_statused(outage=False)
        prior = deepcopy(current_status_records(workspace)["A03"])
        project = deepcopy(workspace["project"])
        next(c for c in project["calendars"] if c["id"] == "DAY")["daily_windows"] = [[28, 34]]
        replace_project(workspace, project)
        _accept(workspace, "A03", "IN_PROGRESS", actual_start=20, actual_periods=[[20, 22]],
                mode_id="SPECIALIST", named_assignments=prior["named_assignments"],
                remaining_processing_ticks=6, supersedes_update_id=prior["id"])
        current = current_status_records(workspace)["A03"]
        self.assertEqual(current["execution_context"], prior["execution_context"])
        entry = next(e for e in propose(workspace)["entries"] if e["activity_id"] == "A03")
        self.assertEqual(entry["actual_periods"], [[20, 22]])
        self.assertEqual(entry["forecast_periods"], [[28, 34]])

    def test_historical_predecessor_finish_must_precede_actual_start(self):
        workspace, _ = named_statused(outage=False)
        prior = current_status_records(workspace)["A01"]
        _accept(workspace, "A01", "COMPLETED", actual_start=14, actual_finish=21,
                actual_periods=[[14, 16]], mode_id="FIXED", named_assignments=[],
                remaining_processing_ticks=0, supersedes_update_id=prior["id"])
        accepted = deepcopy(workspace["execution"])
        with self.assertRaisesRegex(ValueError, "predecessor.*finish|out-of-sequence"):
            propose(workspace)
        self.assertEqual(workspace["execution"], accepted)

    def test_continuous_begun_work_cannot_restart_after_outage(self):
        workspace, _ = named_statused()
        record = current_status_records(workspace)["A03"]
        record["execution_context"]["mode"]["continuity"] = "CONTINUOUS"
        activity = next(a for a in workspace["project"]["activities"] if a["id"] == "A03")
        next(m for m in activity["modes"] if m["id"] == "SPECIALIST")["continuity"] = "CONTINUOUS"
        with self.assertRaisesRegex((ValueError, SchedulingError), "continuous|CONTINUOUS|no executable"):
            propose(workspace)
        self.assertEqual(record["actual_periods"], [[20, 22]])

    def test_group_history_constrains_future_allocation_inside_solver(self):
        workspace = new_blank_workspace()
        p = workspace["project"]
        p.update(horizon_ticks=8, objective_activity_id="H", resources=[], pool_riggers=False)
        p["calendars"] = [{"id": "ALL", "daily_windows": [[0, 48]]},
                          {"id": "X", "daily_windows": [[0, 1], [4, 5], [6, 7]]},
                          {"id": "Y", "daily_windows": [[0, 1], [2, 3]]},
                          {"id": "Z", "daily_windows": [[2, 3], [4, 5], [6, 7]]}]
        p["resource_groups"] = [{"id": "G", "name": "G", "capacity": 2,
                                 "calendar_id": "ALL", "disjoint": True, "interchangeable": True}]
        p["activities"] = [{"id": aid, "name": aid, "predecessors": ["X", "Y", "Z"] if aid == "H" else [],
                            "not_before": 0, "modes": [{"id": "FIXED", "processing_ticks": 0 if aid == "H" else 2,
                            "calendar_id": "ALL" if aid == "H" else aid, "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                            "requirements": [], "group_requirements": [] if aid == "H" else [{"group_id": "G", "demand": 1}]}]}
                           for aid in ("X", "Y", "Z", "H")]
        enable_status_tracking(workspace, 4)
        _accept(workspace, "X", "IN_PROGRESS", actual_start=0, actual_periods=[[0, 1]], mode_id="FIXED", remaining_processing_ticks=1)
        _accept(workspace, "Y", "COMPLETED", actual_start=0, actual_finish=3, actual_periods=[[0, 1], [2, 3]], mode_id="FIXED", remaining_processing_ticks=0)
        _accept(workspace, "Z", "IN_PROGRESS", actual_start=2, actual_periods=[[2, 3]], mode_id="FIXED", remaining_processing_ticks=1)
        _accept(workspace, "H", "NOT_STARTED")
        plan = propose(workspace)
        self.assertEqual(plan["project_finish"], 7)
        entries = {e["activity_id"]: e for e in plan["entries"]}
        self.assertNotEqual(entries["X"]["forecast_periods"], entries["Z"]["forecast_periods"])
        validate_plan(workspace, plan)
        corrupted = deepcopy(plan)
        for e in corrupted["entries"]:
            if e["activity_id"] in ("X", "Z"):
                e.update(start=4, finish=5, forecast_start=4, forecast_finish=5, periods=[[4, 5]], forecast_periods=[[4, 5]])
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "no-handover"):
            validate_plan(workspace, corrupted)

    def test_named_acceptance_control_is_exact_and_begun_mode_is_fixed(self):
        workspace, _ = named_statused()
        plan = propose(workspace)
        entries = {entry["activity_id"]: entry for entry in plan["entries"]}
        self.assertEqual(plan["project_finish"], 63)
        self.assertEqual(plan["selected_modes"]["A03"], "SPECIALIST")
        self.assertEqual(entries["A03"]["actual_periods"], [[20, 22]])
        self.assertEqual(entries["A03"]["forecast_periods"], [[28, 32]])
        self.assertEqual(entries["A04"]["forecast_periods"], [[32, 34]])
        self.assertEqual(entries["A08"]["forecast_periods"], [[62, 63]])
        self.assertEqual(entries["A03"]["actual_assignments"], [["MECH", "M1"], ["SPECIALIST", "M2"]])
        validate_plan(workspace, plan)

    def test_remaining_is_accepted_forecast_not_original_minus_actual(self):
        workspace, _ = named_statused(remaining=5)
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(sum(finish - start for start, finish in entry["actual_periods"]), 2)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 5)
        self.assertNotEqual(6 - 2, 5)

    def test_status_floor_history_immutability_and_future_calendar_change(self):
        workspace, _ = named_statused(outage=False)
        project = deepcopy(workspace["project"])
        next(calendar for calendar in project["calendars"] if calendar["id"] == "DAY")["daily_windows"] = [[28, 34]]
        replace_project(workspace, project)
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["actual_periods"], [[20, 22]])
        self.assertGreaterEqual(entry["forecast_start"], 28)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 4)

    def test_missing_status_is_unknown_and_zero_remaining_is_not_completed(self):
        workspace, _ = named_statused(missing="A08")
        with self.assertRaisesRegex(ValueError, "UNKNOWN: A08"):
            propose(workspace)
        workspace, _ = named_statused(outage=False, remaining=0)
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["execution_state"], "IN_PROGRESS")
        self.assertEqual(entry["forecast_periods"], [])
        self.assertEqual(entry["forecast_start"], 22)

    def test_named_assignment_is_fixed_for_begun_remainder(self):
        workspace, _ = named_statused(outage=False)
        project = deepcopy(workspace["project"])
        resource = next(resource for resource in project["resources"] if resource["id"] == "M1")
        resource["calendar_id"] = "NIGHT"
        replace_project(workspace, project)
        with self.assertRaises(SchedulingError):
            propose(workspace)
        current = current_status_records(workspace, require_complete=True)["A03"]
        self.assertEqual(dict(current["named_assignments"])["MECH"], "M1")

    def test_pooled_continuation_keeps_group_quantity_and_eight_hours(self):
        workspace = pooled_statused()
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "N10")
        self.assertEqual(sum(finish - start for start, finish in entry["actual_periods"]), 8)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 16)
        self.assertEqual(entry["actual_group_demands"], [["ETP", 2]])
        self.assertEqual(entry["group_demands"], [["ETP", 2]])
        self.assertEqual(entry["actual_assignments"], [])
        self.assertFalse(any("@group/" in json.dumps(value) for value in (entry, plan["allocation_witness"])))
        self.assertIsNone(workspace["approved_plan"])
        validate_plan(workspace, plan)

    def test_group_capacity_and_calendar_gap_are_independently_checked(self):
        workspace = pooled_statused()
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "N10")
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 16)
        corrupted = deepcopy(plan)
        corrupted_entry = next(item for item in corrupted["entries"] if item["activity_id"] == "N10")
        corrupted_entry["group_demands"] = [["ETP", 3]]
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "group demands|capacity"):
            validate_plan(workspace, corrupted)

    def test_superseding_correction_wins_by_identity_and_preserves_provenance(self):
        workspace, _ = named_statused(outage=False)
        first_plan = propose(workspace)
        approve(workspace, "recovery-planner")
        prior = current_status_records(workspace)["A03"]
        correction = report_status_update(
            workspace, "A03", "IN_PROGRESS", "correcting-planner", "correct remaining estimate",
            actual_start=20, actual_finish=None, actual_periods=[[20, 22]], mode_id="SPECIALIST",
            named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]], remaining_processing_ticks=6,
            occurred_at=19, supersedes_update_id=prior["id"],
        )
        accept_status_update(workspace, correction, "accepting-planner")
        current = current_status_records(workspace, require_complete=True)["A03"]
        self.assertEqual(current["id"], correction)
        self.assertEqual(current["remaining_processing_ticks"], 6)
        self.assertIn(prior["id"], [update["id"] for update in workspace["execution"]["updates"]])
        self.assertNotEqual(workspace["approved_plan"]["source_state_hash"], state_hash(workspace))
        second_plan = propose(workspace)
        second = next(entry for entry in second_plan["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(second["actual_periods"], [[20, 22]])
        self.assertEqual(sum(finish - start for start, finish in second["forecast_periods"]), 6)
        self.assertNotEqual(first_plan["plan_hash"], second_plan["plan_hash"])

    def test_acceptance_stales_without_auto_approval_and_failed_recovery_retains_facts(self):
        workspace = new_demo_workspace()
        propose(workspace); approve(workspace, "baseline-planner")
        old_approval = deepcopy(workspace["approved_plan"])
        enable_status_tracking(workspace, 22)
        update = report_status_update(workspace, "A01", "COMPLETED", "planner", "first fact",
                                      actual_start=14, actual_finish=16, actual_periods=[[14, 16]], mode_id="FIXED",
                                      named_assignments=[], remaining_processing_ticks=0)
        self.assertEqual(workspace["approved_plan"], old_approval)
        accept_status_update(workspace, update, "planner")
        self.assertEqual(workspace["approved_plan"], old_approval)
        self.assertIsNone(workspace["proposal"])
        self.assertNotEqual(workspace["approved_plan"]["source_state_hash"], state_hash(workspace))

        workspace, _ = named_statused(outage=False)
        accepted_before = deepcopy(workspace["execution"])
        old_approval = deepcopy(workspace["approved_plan"])
        outage = report_unavailable(workspace, "M2", 0, 144, "planner", "synthetic full-horizon outage")
        accept_report(workspace, outage, "planner")
        with self.assertRaises(SchedulingError):
            propose(workspace)
        self.assertEqual(workspace["execution"], accepted_before)
        self.assertEqual(workspace["approved_plan"], old_approval)
        self.assertIsNone(workspace["proposal"])

    def test_multiple_outages_coexist_and_reach_future_calculation(self):
        workspace, _ = named_statused(outage=False)
        ids = []
        for start, finish in ((22, 24), (25, 28)):
            report = report_unavailable(workspace, "M2", start, finish, "planner", "separate accepted outage")
            accept_report(workspace, report, "planner")
            ids.append(report)
        self.assertEqual(ids, ["E001", "E002"])
        self.assertEqual([(r["start"], r["finish"]) for r in workspace["reports"]], [(22, 24), (25, 28)])
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["forecast_periods"], [[28, 32]])

    def test_distinct_named_outages_and_actual_correction_survive_reopen(self):
        workspace, _ = named_statused(outage=False)
        for resource, start, finish in (("M1", 22, 26), ("M2", 26, 28)):
            identifier = report_unavailable(workspace, resource, start, finish, "planner", "synthetic distinct outage")
            accept_report(workspace, identifier, "planner")
        self.assertEqual(len({r["id"] for r in workspace["reports"]}), 2)
        plan = propose(workspace)
        self.assertEqual(next(e for e in plan["entries"] if e["activity_id"] == "A03")["forecast_periods"], [[28, 32]])
        approve(workspace, "test-only")
        prior = deepcopy(current_status_records(workspace)["A03"])
        _accept(workspace, "A03", "IN_PROGRESS", actual_start=21, actual_periods=[[21, 22]], mode_id="SPECIALIST",
                named_assignments=prior["named_assignments"], remaining_processing_ticks=4,
                occurred_at=20, supersedes_update_id=prior["id"])
        workspace["execution"]["updates"].reverse()
        self.assertEqual(current_status_records(workspace)["A03"]["actual_start"], 21)
        self.assertIn(prior, workspace["execution"]["updates"])
        propose(workspace)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "corrected.json"
            save(workspace, destination)
            reopened = load(destination)
            validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)

    def test_save_reopen_preserves_status_history_remaining_and_approvals(self):
        workspace, _ = named_statused()
        propose(workspace); approve(workspace, "recovery-planner")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "statused.pm-workspace.json"
            save(workspace, path)
            reopened = load(path)
            validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)
            self.assertEqual(current_status_records(reopened)["A03"]["remaining_processing_ticks"], 4)
            self.assertEqual(reopened["approved_plan"]["entries"], workspace["approved_plan"]["entries"])

    def test_old_v0_and_v1_workspaces_remain_valid_and_unknown(self):
        version_zero = new_demo_workspace()
        version_one = new_blank_workspace()
        for workspace in (version_zero, version_one):
            validate(workspace)
            with self.assertRaisesRegex(ValueError, "version-two"):
                current_status_records(workspace)
            with TemporaryDirectory() as directory:
                path = Path(directory) / "legacy.json"
                save(workspace, path)
                self.assertEqual(load(path), workspace)

    def test_rehashed_history_and_future_boundary_corruption_is_rejected(self):
        workspace, _ = named_statused()
        plan = propose(workspace)
        corrupted = deepcopy(plan)
        entry = next(entry for entry in corrupted["entries"] if entry["activity_id"] == "A03")
        entry["actual_periods"] = [[21, 23]]
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "rewrites accepted"):
            validate_plan(workspace, corrupted)
        corrupted = deepcopy(plan)
        entry = next(entry for entry in corrupted["entries"] if entry["activity_id"] == "A03")
        entry.update(start=20, finish=24, periods=[[20, 24]], forecast_start=20, forecast_finish=24, forecast_periods=[[20, 24]])
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "status/horizon"):
            validate_plan(workspace, corrupted)

    def test_reported_update_does_not_change_trusted_state(self):
        workspace, _ = named_statused(outage=False)
        before = state_hash(workspace)
        current = current_status_records(workspace)["A03"]
        report_status_update(
            workspace, "A03", "IN_PROGRESS", "planner", "unaccepted draft correction",
            actual_start=20, actual_finish=None, actual_periods=[[20, 22]], mode_id="SPECIALIST",
            named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]], remaining_processing_ticks=8,
            supersedes_update_id=current["id"],
        )
        self.assertEqual(state_hash(workspace), before)
        self.assertEqual(current_status_records(workspace)["A03"]["remaining_processing_ticks"], 4)

    def test_local_and_hosted_status_actions_use_the_same_atomic_workflow(self):
        session = BrowserSession()
        dispatch_action("/api/enable-status", {"status_point": 22}, session)
        payload = {
            "activity_id": "A01", "execution_state": "COMPLETED", "actor": "planner", "reason": "reviewed actual",
            "actual_start": 14, "actual_finish": 16, "actual_periods": [[14, 16]], "mode_id": "FIXED",
            "named_assignments": [], "remaining_processing_ticks": 0, "occurred_at": 16, "supersedes_update_id": None,
        }
        update_id = dispatch_action("/api/status-update", payload, session)["update_id"]
        self.assertEqual(current_status_records(session.workspace), {})
        dispatch_action("/api/accept-status", {"update_id": update_id, "actor": "planner"}, session)
        self.assertEqual(current_status_records(session.workspace)["A01"]["execution_state"], "COMPLETED")

        fresh = BrowserSession()
        state = {"revision": fresh.revision, "dirty": fresh.dirty, "source": fresh.source, "workspace": fresh.workspace}
        status, response = execute({"expected_revision": 0, "state": state, "payload": {"action": "enable-status", "status_point": 22}})
        self.assertEqual(status, 200, response)
        self.assertEqual(response["state"]["workspace"]["schema"], STATUS_SCHEMA)

        def hosted_action(view, action, **fields):
            submitted = {key: view[key] for key in ("revision", "dirty", "source", "workspace")}
            status, result = execute({"expected_revision": submitted["revision"], "state": submitted,
                                      "payload": {"action": action, **fields}})
            self.assertEqual(status, 200, result)
            return result

        reported = hosted_action(response["state"], "status-update", **payload)
        self.assertEqual(current_status_records(reported["state"]["workspace"]), {})
        accepted = hosted_action(reported["state"], "accept-status", update_id=reported["update_id"], actor="planner")
        self.assertEqual(current_status_records(accepted["state"]["workspace"])["A01"]["execution_state"], "COMPLETED")
        for workspace in (named_statused()[0], pooled_statused()):
            opened = hosted_action(accepted["state"], "open", workspace=workspace, filename="synthetic.json")
            calculated = hosted_action(opened["state"], "calculate")
            approved = hosted_action(calculated["state"], "approve", actor="hosted-adapter-test-only")
            exported = hosted_action(approved["state"], "export")
            reopened = hosted_action(exported["state"], "open", workspace=exported["state"]["workspace"], filename="reopened.json")
            self.assertEqual(reopened["state"]["workspace"], exported["state"]["workspace"])
            self.assertEqual(reopened["state"]["approved_status"], "CURRENT")


if __name__ == "__main__":
    unittest.main()
