"""Synthetic capacity/quantity contract; no private workfront source records."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    new_blank_workspace, new_demo_workspace, validate, replace_project, save, load, state_hash,
)
from deterministic_scheduling_core.scheduling.planning_workspace import (
    propose, approve, validate_plan, validate_stored_plans, _plan_hash,
)
from deterministic_scheduling_core.native_planning_ui.server import BrowserSession, dispatch_action, _view
from deterministic_scheduling_core.native_planning_ui.hosted import execute


def group(identifier="CREW", capacity=2, calendar="DAY"):
    return dict(id=identifier, name=f"Interchangeable {identifier}", capacity=capacity,
                calendar_id=calendar, disjoint=True, interchangeable=True)


def fixture():
    w = new_blank_workspace()
    w["schema"] = "pm-native-planning-workspace/1"
    p = w["project"]
    p["resources"] = []
    p["resource_groups"] = [group()]
    p["pool_riggers"] = False
    for i, a in enumerate(p["activities"]):
        a["predecessors"] = [] if i < 7 else [f"N{n:02}" for n in range(1, 8)]
        m = a["modes"][0]
        m["processing_ticks"] = 4 if i < 2 else 0
        m["group_requirements"] = [{"group_id": "CREW", "demand": 1}] if i < 2 else []
    return w


def entries(plan):
    return {e["activity_id"]: e for e in plan["entries"]}


class PlannerResourceCapacityTests(unittest.TestCase):
    def test_anonymized_fifteen_item_reference_preserves_domain_result(self):
        w = fixture(); p = w["project"]
        p.update(id="anonymous-capacity-reference",name="Anonymized quantity regression",horizon_ticks=240,objective_activity_id="A15")
        p["calendars"] = [dict(id="ACT",daily_windows=[[15,31]]),dict(id="RES",daily_windows=[[14,34]])]
        p["resource_groups"] = [group("G1",2,"RES"),group("G2",2,"RES")]
        ticks = [6,4,8,6,4,4,0,2,6,20,6,2,0,6,0]
        predecessors = [[],[],[2],[3],[4],[5],[6],[],[8],[9],[10],[11],[12],[],[1,7,13,14]]
        p["activities"] = []
        for i, (duration, predecessors) in enumerate(zip(ticks,predecessors),1):
            gid = "G2" if i in (2,6,10) else "G1"
            demand = 1 if i in (2,6) else 2
            p["activities"].append(dict(id=f"A{i:02}",name=f"Operation {i}",predecessors=[f"A{j:02}" for j in predecessors],not_before=0,
                modes=[dict(id="FIXED",processing_ticks=duration,calendar_id="ACT",continuity="SUSPENDABLE_AT_AVAILABILITY_GAPS",
                            requirements=[],group_requirements=[dict(group_id=gid,demand=demand)] if duration else [])]))
        legacy = deepcopy(w); legacy["schema"] = "pm-native-planning-workspace/0"
        legacy["project"].pop("resource_groups")
        legacy["project"]["resources"] = [dict(id=f"{g}{n}",capabilities=[g],calendar_id="RES") for g in ("G1","G2") for n in (1,2)]
        for a in legacy["project"]["activities"]:
            m=a["modes"][0]
            for r in m.pop("group_requirements"):
                m["requirements"] = [dict(id=f"slot{n}",pool_ids=[r["group_id"]],eligible_resource_ids=[f"{r['group_id']}1",f"{r['group_id']}2"]) for n in range(r["demand"])]
        first = propose(legacy); second = deepcopy(propose(w))
        self.assertEqual(first["objective"], [125,0,0,0,9038])
        self.assertEqual(second["objective"], first["objective"])
        for a,b in zip(first["entries"], second["entries"]):
            for key in ("activity_id","start","finish","periods"): self.assertEqual(a[key],b[key])
        self.assertEqual(second,propose(w))
        self.assertEqual(sum(ticks)/2,37)
        self.assertEqual(sum(m["processing_ticks"]*sum(r["demand"] for r in m["group_requirements"]) for a in p["activities"] for m in a["modes"])/2,70)

    def test_new_project_has_no_synthetic_roster(self):
        w = new_blank_workspace()
        self.assertEqual(w["schema"], "pm-native-planning-workspace/1")
        self.assertEqual(w["project"]["resources"], [])
        self.assertEqual(w["project"]["resource_groups"], [])

    def test_capacity_two_permits_two_simultaneous_quantity_one_jobs(self):
        w = fixture()
        p = propose(w)
        self.assertEqual(p["project_finish"], 18)
        self.assertEqual(entries(p)["N01"]["start"], entries(p)["N02"]["start"])
        self.assertEqual(entries(p)["N01"]["group_demands"], [["CREW", 1]])
        self.assertEqual(entries(p)["N01"]["assignments"], [])
        self.assertEqual(p["allocation_witness"], [])
        self.assertEqual(p["physical_status"], "PROVEN_FEASIBLE")
        validate_plan(w, p)

    def test_quantity_two_and_capacity_edits_affect_dates_not_duration(self):
        w = fixture()
        before = propose(w)
        w["project"]["activities"][0]["modes"][0]["group_requirements"][0]["demand"] = 2
        after = propose(w)
        self.assertEqual(after["project_finish"], 22)
        for e in after["entries"][:2]:
            self.assertEqual(sum(b-a for a,b in e["periods"]), 4)
        w = fixture()
        w["project"]["resource_groups"][0]["capacity"] = 1
        self.assertEqual(propose(w)["project_finish"], 22)
        self.assertEqual(before["project_finish"], 18)

    def test_invalid_quantity_capacity_and_declared_overlap_are_rejected(self):
        for bad in (0, -1, 1.5, True, "2", 3):
            w = fixture()
            w["project"]["activities"][0]["modes"][0]["group_requirements"][0]["demand"] = bad
            with self.subTest(demand=bad), self.assertRaises(ValueError): validate(w)
        for bad in (0, -1, 1.5, True, "2"):
            w = fixture(); w["project"]["resource_groups"][0]["capacity"] = bad
            with self.subTest(capacity=bad), self.assertRaises(ValueError): validate(w)
        for edit in ({"disjoint": False}, {"interchangeable": False}, {"member_resource_ids": ["M1"]}):
            w = fixture(); w["project"]["resource_groups"][0].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError): validate(w)
        w = fixture()
        w["project"]["resources"] = [dict(id="CREW", calendar_id="DAY", capabilities=["MECH"])]
        with self.assertRaises(ValueError): validate(w)

    def test_duplicate_demand_and_milestone_demand_rejected(self):
        w = fixture(); m = w["project"]["activities"][0]["modes"][0]
        m["group_requirements"] *= 2
        with self.assertRaises(ValueError): validate(w)
        w = fixture(); w["project"]["activities"][0]["modes"][0]["processing_ticks"] = 0
        with self.assertRaisesRegex(ValueError, "milestone"): validate(w)

    def test_multiple_groups_and_their_calendars_are_joint_requirements(self):
        w = fixture(); p = w["project"]
        p["calendars"].append(dict(id="LATE", daily_windows=[[16, 20]]))
        p["resource_groups"].append(group("TOOL", 1, "LATE"))
        for a in p["activities"][:2]:
            a["modes"][0]["group_requirements"].append(dict(group_id="TOOL", demand=1))
        result = propose(w)
        self.assertEqual(sorted(e["periods"] for e in result["entries"][:2]), [[[16,20]], [[64,68]]])
        validate_plan(w, result)

    def test_suspension_releases_group_capacity_and_continuity_is_preserved(self):
        w = fixture(); p = w["project"]
        p["resource_groups"][0]["capacity"] = 1
        p["calendars"] = [dict(id="DAY", daily_windows=[[14,24]]),
                          dict(id="GAP", daily_windows=[[14,16],[20,24]])]
        a, b = p["activities"][:2]
        a["modes"][0]["calendar_id"] = "GAP"
        b["not_before"] = 16
        result = propose(w)
        self.assertEqual(entries(result)["N01"]["periods"], [[14,16],[20,22]])
        self.assertEqual(entries(result)["N02"]["periods"], [[16,20]])
        a["modes"][0]["continuity"] = "CONTINUOUS"
        result = propose(w)
        self.assertEqual(entries(result)["N01"]["periods"], [[20,24]])

    def test_named_slots_coexist_and_keep_fixed_assignment(self):
        w = fixture(); p = w["project"]
        p["resources"] = [dict(id="TOOL", capabilities=["LIFT", "INSPECT"], calendar_id="DAY")]
        for a in p["activities"][:2]:
            a["modes"][0]["requirements"] = [dict(id="specific", pool_ids=["LIFT","INSPECT"], eligible_resource_ids=["TOOL"])]
        result = propose(w)
        self.assertEqual(result["project_finish"], 22)
        self.assertEqual(entries(result)["N01"]["assignments"], [["specific","TOOL"]])
        validate_stored_plans(w)

    def test_aggregate_capacity_does_not_silently_allow_mid_activity_handovers(self):
        w = fixture(); p = w["project"]; p["horizon_ticks"] = 48
        p["calendars"].extend([dict(id="SPLIT", daily_windows=[[14,16],[18,20]]),
                              dict(id="EARLY", daily_windows=[[14,18]]),
                              dict(id="LATE", daily_windows=[[16,20]])])
        for a, cal in zip(p["activities"][:3], ["SPLIT","EARLY","LATE"]):
            a["modes"][0].update(calendar_id=cal, processing_ticks=4,
                                group_requirements=[dict(group_id="CREW",demand=1)])
        # Pairwise conflicts form a triangle, although no tick needs >2 units.
        # A fixed unit through all productive periods requires three colours.
        with self.assertRaises(SchedulingError): propose(w)
        p["resource_groups"][0]["capacity"] = 3
        plan = propose(w)
        p["resource_groups"][0]["capacity"] = 2
        from deterministic_scheduling_core.project.planning_workspace import trusted_input
        plan["source_snapshot"] = trusted_input(w); plan["source_state_hash"] = state_hash(w)
        plan["plan_hash"] = _plan_hash(plan)
        with self.assertRaisesRegex(ValueError,"assignable"): validate_plan(w, plan)

    def test_independent_checker_rejects_rehashed_capacity_corruption(self):
        w = fixture(); w["project"]["resource_groups"][0]["capacity"] = 1
        p = propose(w); a,b = p["entries"][:2]
        b.update(start=a["start"], finish=a["finish"], periods=deepcopy(a["periods"]))
        p["plan_hash"] = _plan_hash(p)
        with self.assertRaisesRegex(ValueError, "capacity|assignable"): validate_plan(w,p)

    def test_independent_checker_rejects_changed_demand_and_arbitrary_pause(self):
        w = fixture(); p = propose(w)
        p["entries"][0]["group_demands"] = [["CREW",2]]; p["plan_hash"] = _plan_hash(p)
        with self.assertRaisesRegex(ValueError, "demand"): validate_plan(w,p)
        p = propose(w); p["entries"][0].update(periods=[[14,16],[17,19]], finish=19)
        p["plan_hash"] = _plan_hash(p)
        with self.assertRaisesRegex(ValueError, "suspension"): validate_plan(w,p)

    def test_anonymous_permutations_are_not_assignment_changes(self):
        w = fixture(); baseline = deepcopy(propose(w)); approve(w,"agent-test")
        p = deepcopy(w["project"]); p["resource_groups"][0]["capacity"] = 3
        replace_project(w,p)
        result = propose(w)
        self.assertEqual(result["objective"][1:4], [0,0,0])
        self.assertEqual(result["entries"], baseline["entries"])
        self.assertEqual(result, propose(w))

    def test_new_and_legacy_save_reopen_preserves_hashes_and_history(self):
        for w in (fixture(), new_demo_workspace()):
            propose(w); approve(w,"agent-test")
            old = deepcopy(w["approved_plan"])
            p = deepcopy(w["project"]); p["name"] += " edited"
            replace_project(w,p); propose(w); approve(w,"agent-test-recovery")
            with TemporaryDirectory() as d:
                path = Path(d)/"workspace.json"; save(w,path)
                reopened = load(path); validate_stored_plans(reopened)
                self.assertEqual(reopened, w)
                self.assertEqual(reopened["plan_history"], [old])

    def test_legacy_schema_cannot_silently_accept_new_fields(self):
        w = fixture(); w["schema"] = "pm-native-planning-workspace/0"
        with self.assertRaises(ValueError): validate(w)

    def test_apply_failures_stale_approval_and_infeasibility_retain_state(self):
        w = fixture(); propose(w); approve(w,"agent-test")
        before = deepcopy(w)
        p = deepcopy(w["project"]); p["resource_groups"][0]["capacity"] = 0
        with self.assertRaises(ValueError): replace_project(w,p)
        self.assertEqual(w,before)
        p = deepcopy(w["project"]); p["calendars"][0]["daily_windows"] = []
        replace_project(w,p)
        with self.assertRaises(SchedulingError): propose(w)
        self.assertEqual(w["approved_plan"], before["approved_plan"])
        validate_stored_plans(w)

    def test_pool_outage_is_explicitly_unsupported_not_a_fake_person_report(self):
        session = BrowserSession(workspace=fixture()); before = deepcopy(session.workspace)
        with self.assertRaisesRegex(ValueError, "group|resource"):
            dispatch_action("/api/report", dict(resource_id="CREW",start=14,finish=18,reporter="agent",reason="test"),session)
        self.assertEqual(session.workspace,before)

    def test_hosted_stateless_group_lifecycle(self):
        state = _view(BrowserSession(workspace=fixture()))
        for payload in ({"action":"calculate"}, {"action":"approve","actor":"agent-test"}, {"action":"export"}):
            request = dict(expected_revision=state["revision"], state={k:state[k] for k in ("revision","dirty","source","workspace")},payload=payload)
            original = deepcopy(request)
            status,response = execute(request)
            self.assertEqual(status,200,response)
            self.assertEqual(request,original)
            state = json.loads(json.dumps(response["state"]))
        self.assertEqual(state["approved_status"],"CURRENT")
        self.assertIsNone(state["workspace"]["proposal"])


if __name__ == "__main__": unittest.main()
