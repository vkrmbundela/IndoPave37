
import pytest
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.optimizer.problem import OptimizationProblem, OptimizationResult
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel
from mep_opt.solver.legacy_bridge import is_bridge_available

bridge_required = pytest.mark.skipif(
    not is_bridge_available(),
    reason="Legacy bridge executable not available"
)


@bridge_required
def test_optimizer_run():
    """Smart search finds adequate designs within bounds."""
    traffic = TrafficInput(
        initial_aadt=0,
        commercial_vehicles_per_day=3000,
        traffic_growth_rate=0.0,
        design_life_years=20,
        lane_distribution_factor=1.0,
        vehicle_damage_factor=1.0,
    )

    subgrade = SubgradeInput(cbr=8.0)

    problem = OptimizationProblem(
        traffic=traffic,
        subgrade=subgrade,
        reliability=ReliabilityLevel.R90,
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC": (30, 50),
            "DBM": (50, 100),
            "WMM": (150, 250),
            "GSB": (150, 250),
        },
    )

    optimizer = SmartPavementSearch(problem)
    result = optimizer.run()

    assert isinstance(result, OptimizationResult)
    assert len(result.optimal_thicknesses) == 4
    assert result.cost > 0

    # Thicknesses must respect bounds
    for i, t in enumerate(result.optimal_thicknesses):
        l_type = problem.layer_types[i]
        lo, hi = problem.thickness_bounds[l_type]
        assert lo <= t <= hi, f"{l_type} thickness {t} outside [{lo}, {hi}]"

    # Must have at least Economy archetype
    assert result.pareto_front is not None
    assert len(result.pareto_front) >= 1

    # Economy should be the thinnest
    econ = result.pareto_front[0]
    assert econ.performance.get("strategy") == "Economy"
    assert econ.performance.get("overall_adequate") is True

    print(f"Optimal Thicknesses: {result.optimal_thicknesses}")
    print(f"Cost: {result.cost}")
    print(f"Archetypes: {len(result.pareto_front)}")
