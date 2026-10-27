import json

from support_analytics.eval.runner import SCENARIOS, run_invariants, run_scenario


def test_every_scenario_passes_exactly() -> None:
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    assert len(scenarios) >= 14 and len({s["id"] for s in scenarios}) == len(scenarios)
    results = [run_scenario(s) for s in scenarios]
    assert [r["id"] for r in results if not r["passed"]] == []
    assert sum(r["checks"] for r in results) >= 75


def test_invariants_hold_on_random_data() -> None:
    results = run_invariants(range(1, 6))
    assert all(r["passed"] for r in results), [r for r in results if not r["passed"]]


def test_a_wrong_expectation_is_caught() -> None:
    """The evaluator itself must fail when an expectation is wrong."""
    scenario = json.loads(SCENARIOS.read_text(encoding="utf-8"))[0]
    scenario["expect"]["c1#1"]["first_response_min"] = 31.0
    assert not run_scenario(scenario)["passed"]
