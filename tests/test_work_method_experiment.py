import unittest

from deterministic_scheduling_core.work_method_experiment import (
    build_case,
    decision_explanations,
    render,
    run_experiment,
)


class WorkMethodExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_experiment()

    def test_case_has_research_recommended_shape(self) -> None:
        case = build_case()
        self.assertEqual(len(case.packages), 6)
        self.assertEqual(case.fixed_network_count, 8)
        self.assertEqual(case.possible_activity_count, 33)

    def test_candidate_matches_exhaustive_fixed_network_oracle(self) -> None:
        self.assertFalse(self.result.falsified)
        self.assertTrue(all(item.matches_oracle for item in self.result.scenarios))
        self.assertEqual(
            {item.scenario.id: item.candidate.objective_finish for item in self.result.scenarios},
            {"A": 37, "B": 41, "C": 35},
        )

    def test_changed_conditions_reselect_authorised_methods(self) -> None:
        methods = {
            item.scenario.id: item.candidate.methods_by_package
            for item in self.result.scenarios
        }
        self.assertEqual(methods["A"]["WP-B"], "SCAFFOLD")
        self.assertEqual(methods["A"]["WP-C"], "CRANE")
        self.assertEqual(methods["A"]["WP-D"], "NORMAL")
        self.assertEqual(methods["B"]["WP-C"], "SEGMENTED")
        self.assertEqual(methods["C"]["WP-B"], "ROPE")
        self.assertEqual(methods["C"]["WP-D"], "SPECIALIST")

    def test_workface_exclusion_is_respected_in_segmented_method(self) -> None:
        scenario_b = self.result.by_scenario["B"].candidate
        east = scenario_b.by_id["C2-2"]
        west = scenario_b.by_id["C2-3"]
        self.assertTrue(east.finish <= west.start or west.finish <= east.start)

    def test_candidate_representation_is_compacter_and_explainable(self) -> None:
        self.assertLess(
            self.result.candidate_activity_facts,
            self.result.enumerated_activity_facts,
        )
        self.assertLess(
            self.result.candidate_relationship_facts,
            self.result.enumerated_relationship_facts,
        )
        baseline = self.result.by_scenario["A"].candidate
        b = self.result.by_scenario["B"]
        c = self.result.by_scenario["C"]
        self.assertTrue(any("CRANE" in text for text in decision_explanations(baseline, b.candidate, b.scenario)))
        c_text = "\n".join(decision_explanations(baseline, c.candidate, c.scenario))
        self.assertIn("permit", c_text)
        self.assertIn("specialist", c_text)
        self.assertIn("NOT FALSIFIED", render(self.result))


if __name__ == "__main__":
    unittest.main()
