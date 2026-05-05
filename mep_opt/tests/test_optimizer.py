
import pytest
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.optimizer.problem import OptimizationProblem, OptimizationResult
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel
from mep_opt.solver.legacy_bridge import is_bridge_available
from mep_opt.cost import DEFAULT_MATERIAL_RATES, MaterialRate

bridge_required = pytest.mark.skipif(
    not is_bridge_available(),
    reason="Legacy bridge executable not available"
)


def _stub_problem(material_rates=None):
    """Build a minimal OptimizationProblem for resolver tests (no bridge call)."""
    return OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=1000,
            traffic_growth_rate=0.0,
            design_life_years=15,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        material_rates=material_rates,
    )


# --- material_rates resolver: pure-Python tests, no bridge required ---

def test_resolved_rates_default_when_none():
    """No override → caller gets the full IRC/MORTH default table."""
    resolved = _stub_problem(material_rates=None).resolved_material_rates()
    assert resolved["BC"].cost_per_cum == DEFAULT_MATERIAL_RATES["BC"].cost_per_cum
    assert resolved["GSB"].cost_per_cum == DEFAULT_MATERIAL_RATES["GSB"].cost_per_cum


def test_resolved_rates_scalar_override_keeps_other_fields():
    """A bare number overrides only cost_per_cum; CO₂ and density stay at defaults."""
    resolved = _stub_problem(material_rates={"BC": 14000}).resolved_material_rates()
    assert resolved["BC"].cost_per_cum == 14000
    assert resolved["BC"].co2_per_cum == DEFAULT_MATERIAL_RATES["BC"].co2_per_cum
    assert resolved["BC"].density == DEFAULT_MATERIAL_RATES["BC"].density
    # Non-overridden layers untouched
    assert resolved["GSB"].cost_per_cum == DEFAULT_MATERIAL_RATES["GSB"].cost_per_cum


def test_resolved_rates_partial_dict_override():
    """A partial dict overrides only the specified fields."""
    resolved = _stub_problem(material_rates={
        "DBM": {"cost_per_cum": 11500, "co2_per_cum": 175}
    }).resolved_material_rates()
    assert resolved["DBM"].cost_per_cum == 11500
    assert resolved["DBM"].co2_per_cum == 175
    # density should still be the default
    assert resolved["DBM"].density == DEFAULT_MATERIAL_RATES["DBM"].density


def test_resolved_rates_full_material_rate_object():
    """A complete MaterialRate object replaces the entry wholesale."""
    custom = MaterialRate("Custom GSB", cost_per_cum=2200, co2_per_cum=28, density=2050)
    resolved = _stub_problem(material_rates={"GSB": custom}).resolved_material_rates()
    assert resolved["GSB"] is custom


def test_resolved_rates_case_insensitive_keys():
    """Lowercase user keys still match uppercase material codes."""
    resolved = _stub_problem(material_rates={"bc": 13000}).resolved_material_rates()
    assert resolved["BC"].cost_per_cum == 13000


def test_resolved_rates_unknown_layer_added():
    """Override for a layer not in defaults still produces an entry."""
    resolved = _stub_problem(material_rates={"NEWMIX": 9000}).resolved_material_rates()
    assert "NEWMIX" in resolved
    assert resolved["NEWMIX"].cost_per_cum == 9000


# --- Issue #5: thickness_bounds completeness validator ---

def test_thickness_bounds_must_cover_all_layers():
    """User-supplied thickness_bounds missing a layer is a hard error, not silent default."""
    with pytest.raises(ValueError, match="missing entries for layer_types"):
        OptimizationProblem(
            traffic=TrafficInput(
                initial_aadt=0,
                commercial_vehicles_per_day=1000,
                traffic_growth_rate=0.0,
                design_life_years=15,
            ),
            subgrade=SubgradeInput(cbr=8.0),
            layer_types=["BC", "DBM", "CTB", "WMM"],
            thickness_bounds={
                "BC":  (30, 50),
                "DBM": (50, 150),
                "WMM": (150, 300),
                # CTB intentionally absent — must be flagged
            },
        )


def test_thickness_bounds_inverted_range_rejected():
    """min > max in thickness_bounds is a hard error."""
    with pytest.raises(ValueError, match="min .* > max"):
        OptimizationProblem(
            traffic=TrafficInput(
                initial_aadt=0,
                commercial_vehicles_per_day=1000,
                traffic_growth_rate=0.0,
                design_life_years=15,
            ),
            subgrade=SubgradeInput(cbr=8.0),
            layer_types=["BC", "DBM"],
            thickness_bounds={
                "BC":  (60, 30),  # inverted!
                "DBM": (50, 150),
            },
        )


def test_thickness_bounds_default_when_none():
    """When thickness_bounds=None the auto-generated defaults are used; no error."""
    p = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=1000,
            traffic_growth_rate=0.0,
            design_life_years=15,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds=None,  # default path
    )
    assert "BC" in p.thickness_bounds
    assert p.thickness_bounds["BC"] == (30, 50)


# --- Issue #17: layer-stack validation in OptimizeRequest ---

def test_optimize_request_rejects_duplicate_layer_types():
    """Duplicate layer_types make layer_props ambiguous — must be rejected at the API."""
    from mep_opt.web.main import OptimizeRequest, LayerConstraint
    layer = lambda lt: LayerConstraint(
        layer_type=lt, min_thickness=30, max_thickness=50,
        is_fixed=False, fixed_thickness=0, E=1250, nu=0.35,
    )
    with pytest.raises(ValueError, match="Duplicate"):
        OptimizeRequest(
            cvpd=1000, growth_rate=0.05, design_life=15,
            subgrade_cbr=8.0,
            layers=[layer("BC"), layer("BC")],  # duplicate!
        )


def test_optimize_request_rejects_empty_layers():
    """Empty layers list cannot produce a valid pavement structure."""
    from mep_opt.web.main import OptimizeRequest
    with pytest.raises(ValueError, match="At least one layer"):
        OptimizeRequest(
            cvpd=1000, growth_rate=0.05, design_life=15,
            subgrade_cbr=8.0,
            layers=[],
        )


# --- Issue #15: wheel-field range validators ---

def test_optimize_request_rejects_implausible_wheel_load():
    """A 1e9 N wheel load is outside the engineering range; must be flagged."""
    from mep_opt.web.main import OptimizeRequest, LayerConstraint
    layer = LayerConstraint(
        layer_type="BC", min_thickness=30, max_thickness=50,
        is_fixed=False, fixed_thickness=0, E=1250, nu=0.35,
    )
    with pytest.raises(ValueError, match="wheel_load"):
        OptimizeRequest(
            cvpd=1000, growth_rate=0.05, design_life=15,
            subgrade_cbr=8.0,
            wheel_load=1e9,
            layers=[layer],
        )


def test_optimizer_emits_growth_and_reliability_warnings():
    """Sub-5% growth and high-MSA R80 both deserve non-fatal warnings."""
    import mep_opt.optimizer.smart_search as ss

    problem = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=3000,
            traffic_growth_rate=0.04,
            design_life_years=20,
            lane_distribution_factor=0.75,
            vehicle_damage_factor=2.5,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        reliability=ReliabilityLevel.R80,
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC": (30, 50),
            "DBM": (50, 100),
            "WMM": (150, 250),
            "GSB": (150, 250),
        },
    )

    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = SmartPavementSearch(problem)
    finally:
        ss.is_bridge_available = orig

    warnings = opt._build_warnings()
    assert any("below 5%" in w for w in warnings)
    assert any("R90" in w for w in warnings)


def test_ctb_spectrum_routes_through_check_ctb_adequacy():
    """CTB axle spectra should be scored by the spectrum helper, not a scalar shortcut."""
    import mep_opt.optimizer.smart_search as ss
    from mep_opt.solver.irc37 import AxleLoadGroup

    problem = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=3000,
            traffic_growth_rate=0.05,
            design_life_years=20,
            lane_distribution_factor=0.75,
            vehicle_damage_factor=2.5,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        reliability=ReliabilityLevel.R90,
        layer_types=["BC", "DBM", "WMM", "CTB", "GSB"],
        thickness_bounds={
            "BC": (40, 40),
            "DBM": (60, 60),
            "WMM": (150, 150),
            "CTB": (150, 150),
            "GSB": (150, 150),
        },
        has_sami=False,
        ctb_axle_spectrum=[
            AxleLoadGroup("single", 20.0, 1000.0),
            AxleLoadGroup("tandem", 40.0, 500.0),
        ],
        ctb_per_class_bridge_recompute=False,
    )

    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = SmartPavementSearch(problem)
    finally:
        ss.is_bridge_available = orig

    def fake_bridge(stack, load_cfg, eval_points):
        pressure = load_cfg["pressure"]
        load = load_cfg["load"]
        sigma_t = (load / 10000.0) * (1.0 if pressure < 0.8 else 1.1)
        result = {
            "sigma_t": sigma_t,
            "eps_t": 150e-6,
            "eps_r": 120e-6,
            "eps_z": 300e-6,
            "sigma_z": 0.0,
            "sigma_r": 0.0,
            "tau_rz": 0.0,
            "disp_z": 0.0,
            "disp_r": 0.0,
        }
        return [dict(result, z=pt["z"], r=pt["r"]) for pt in eval_points]

    opt._bridge_call = fake_bridge  # type: ignore[method-assign]
    result = opt._evaluate([40.0, 60.0, 150.0, 150.0, 150.0])

    assert result["CDF_ctb"] is not None
    assert result["ctb_details"]["details"][0]["load_kn"] == 20.0
    assert result["ctb_details"]["details"][1]["load_kn"] == 40.0
    assert result["ctb_adequate"] in (True, False)


# --- Issue #13: optimizer-level deadline ---

@bridge_required
def test_optimizer_respects_already_passed_deadline():
    """A deadline already in the past must short-circuit run() immediately."""
    import time as _time

    problem = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=3000,
            traffic_growth_rate=0.0,
            design_life_years=20,
            lane_distribution_factor=1.0,
            vehicle_damage_factor=1.0,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        reliability=ReliabilityLevel.R90,
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC":  (30, 50),
            "DBM": (50, 100),
            "WMM": (150, 250),
            "GSB": (150, 250),
        },
    )
    optimizer = SmartPavementSearch(problem)

    # Set a deadline 1s in the past — first deadline check must trip
    # before any bridge call. The whole run should finish in under 2s
    # (the bridge availability check + a few python-level operations).
    past_deadline = _time.monotonic() - 1.0

    t0 = _time.monotonic()
    result = optimizer.run(deadline=past_deadline)
    elapsed = _time.monotonic() - t0

    assert elapsed < 5.0, f"Past-deadline run should be near-instant, took {elapsed:.2f}s"
    # is_feasible may be True or False depending on whether at least one
    # evaluation slipped through before the check; what matters is that
    # we did NOT spend the full 100s of a normal optimization.
    assert isinstance(result, OptimizationResult)


def test_optimizer_run_accepts_timeout_and_deadline():
    """Both `timeout` and `deadline` must be accepted as keyword arguments."""
    import inspect
    sig = inspect.signature(SmartPavementSearch.run)
    assert "timeout" in sig.parameters
    assert "deadline" in sig.parameters
    assert sig.parameters["timeout"].default is None
    assert sig.parameters["deadline"].default is None


# ----------------------------------------------------------------------
# Severity-2 architecture: lift schedule, brute-force, Pareto, Kneedle,
# premium-ceiling Premium semantics.
# ----------------------------------------------------------------------

def _result(thicknesses, cost, cdf, ctb=None):
    """Helper — minimal evaluation result for archetype selection."""
    return {
        "thicknesses": list(thicknesses),
        "total_thickness": sum(thicknesses),
        "cost_per_km": cost,
        "co2_per_km": 0.0,
        "CDF_fatigue": cdf,
        "CDF_rutting": 0.0,
        "CDF_ctb": ctb,
        "overall_adequate": True,
    }


def test_pareto_front_drops_dominated_points():
    """A point that's both more expensive AND has higher CDF must be dropped."""
    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95),  # cheap, high-CDF — on front
        _result([30, 75, 150, 200], 70e5, 0.60),  # on front
        _result([30, 75, 200, 200], 80e5, 0.40),  # on front
        _result([35, 60, 150, 150], 55e5, 0.97),  # DOMINATED by #1
        _result([40, 80, 200, 250], 90e5, 0.50),  # DOMINATED by #3
    ]
    front = SmartPavementSearch._pareto_front(designs)
    front_costs = sorted(d["cost_per_km"] for d in front)
    assert front_costs == [50e5, 70e5, 80e5]


def test_pareto_front_orders_by_ascending_cost_descending_cdf():
    """The front must come out as the canonical Pareto curve."""
    designs = [
        _result([50, 100, 250, 250], 110e5, 0.15),
        _result([30, 50,  150, 150], 50e5,  0.95),
        _result([30, 75,  200, 200], 80e5,  0.40),
        _result([40, 90,  250, 250], 95e5,  0.25),
    ]
    front = SmartPavementSearch._pareto_front(designs)
    costs = [d["cost_per_km"] for d in front]
    cdfs = [SmartPavementSearch._governing_cdf(d) for d in front]
    assert costs == sorted(costs)             # cost ascending
    assert cdfs == sorted(cdfs, reverse=True) # CDF descending


def test_kneedle_picks_inflection_not_endpoints():
    """The knee must be an interior point, not Economy or Premium."""
    front = [
        _result([30, 50, 150, 150], 50e5, 0.95),  # Economy end
        _result([30, 60, 150, 150], 55e5, 0.85),
        _result([30, 75, 200, 200], 80e5, 0.40),  # the knee — sharp drop ends here
        _result([40, 90, 250, 250], 95e5, 0.25),
        _result([50, 100, 250, 250], 110e5, 0.15),  # Premium end
    ]
    knee = SmartPavementSearch._kneedle_balanced(front)
    assert knee is not None
    assert knee["thicknesses"] not in (front[0]["thicknesses"], front[-1]["thicknesses"])


def test_kneedle_returns_none_for_short_front():
    """Two-point front has no interior — Kneedle should bail out."""
    front = [_result([30, 50, 150, 150], 50e5, 0.95),
             _result([50, 100, 250, 250], 110e5, 0.15)]
    assert SmartPavementSearch._kneedle_balanced(front) is None


def test_layer_lift_values_filters_to_bounds():
    """Lift schedule values outside bounds must be excluded."""
    problem = _stub_problem()
    optimizer_cls = SmartPavementSearch
    # Build a SmartPavementSearch instance lite-style for the helper test —
    # bypass the bridge-availability check by monkey-patching.
    import mep_opt.optimizer.smart_search as ss
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = optimizer_cls(problem)
    finally:
        ss.is_bridge_available = orig

    # BC schedule = [30, 40, 50]. With bounds (35, 50), only 40 and 50 qualify.
    assert opt._layer_lift_values("BC", 35, 50) == [40.0, 50.0]
    # DBM schedule = [50, 60, 65, 75, 90, 100, 130, 150]; bounds (60, 100):
    assert opt._layer_lift_values("DBM", 60, 100) == [60.0, 65.0, 75.0, 90.0, 100.0]
    # Fixed layer (lo == hi) returns exactly the value
    assert opt._layer_lift_values("BC", 40, 40) == [40.0]
    # Layer not in schedule — falls back to 5mm grid
    assert opt._layer_lift_values("UNKNOWN", 30, 40) == [30.0, 35.0, 40.0]


def test_layer_lift_values_falls_back_when_schedule_misses_bounds():
    """If bounds carve out a region with no lift values, fall back to 5mm grid."""
    problem = _stub_problem()
    import mep_opt.optimizer.smart_search as ss
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = SmartPavementSearch(problem)
    finally:
        ss.is_bridge_available = orig

    # BC schedule = [30, 40, 50]; bounds (33, 38) excludes them all.
    # Fallback grid: 33, 38
    out = opt._layer_lift_values("BC", 33, 38)
    assert out[0] == 33.0
    assert out[-1] == 38.0


def test_archetype_selection_uses_premium_ceiling():
    """Premium must be the cheapest design with CDF ≤ premium_cdf_ceiling,
    not the lowest-CDF design overall."""
    problem = _stub_problem()
    problem.premium_cdf_ceiling = 0.6
    import mep_opt.optimizer.smart_search as ss
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = SmartPavementSearch(problem)
    finally:
        ss.is_bridge_available = orig

    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95),  # Economy
        _result([30, 75, 200, 200], 80e5, 0.40),  # cheapest under 0.6 ceiling — Premium
        _result([40, 90, 250, 250], 95e5, 0.25),  # also under ceiling but more expensive
        _result([50, 100, 250, 250], 110e5, 0.15),  # absolute lowest CDF — but NOT Premium
    ]
    archetypes = opt._select_archetypes(designs)
    labels = {a.performance["strategy"]: a for a in archetypes}
    assert "Premium" in labels
    assert labels["Premium"].cost == 80e5  # the 0.40-CDF design at 80L
    # Critically, Premium is NOT the absolute-lowest-CDF design (110L)
    assert labels["Premium"].cost != 110e5


def test_ctb_without_crack_relief_or_sami_is_rejected():
    """
    IRC 37:2018 page 28 / §8.3: when CTB is in the stack, a crack relief
    layer (aggregate interlayer or SAMI) must sit between the bituminous
    bundle and the CTB.
    """
    with pytest.raises(ValueError, match="crack relief"):
        OptimizationProblem(
            traffic=TrafficInput(
                initial_aadt=0, commercial_vehicles_per_day=2000,
                traffic_growth_rate=0.05, design_life_years=20,
            ),
            subgrade=SubgradeInput(cbr=8.0),
            # BC sits directly on CTB — no crack relief
            layer_types=["BC", "DBM", "CTB", "GSB"],
            thickness_bounds={
                "BC": (40, 50), "DBM": (50, 100),
                "CTB": (150, 200), "GSB": (150, 250),
            },
        )


def test_ctb_with_sami_flag_passes_validator():
    """has_sami=True satisfies the crack-relief requirement."""
    p = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0, commercial_vehicles_per_day=2000,
            traffic_growth_rate=0.05, design_life_years=20,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "CTB", "GSB"],
        thickness_bounds={
            "BC": (40, 50), "DBM": (50, 100),
            "CTB": (150, 200), "GSB": (150, 250),
        },
        has_sami=True,
    )
    assert p.has_sami is True


def test_ctb_with_aggregate_interlayer_passes_validator():
    """A WMM (aggregate crack relief) above CTB satisfies the requirement."""
    p = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0, commercial_vehicles_per_day=2000,
            traffic_growth_rate=0.05, design_life_years=20,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        # WMM sits between bituminous bundle and CTB → satisfies §8.3
        layer_types=["BC", "DBM", "WMM", "CTB", "GSB"],
        thickness_bounds={
            "BC": (40, 50), "DBM": (50, 100),
            "WMM": (100, 150), "CTB": (150, 200), "GSB": (150, 250),
        },
    )
    assert "CTB" in p.layer_types


def test_traffic_tier_minimum_filter_blocks_thin_designs():
    """
    For >20 MSA the BC ≥ 40mm and bundle ≥ 100mm rules must drop combos
    that fall below those thresholds. Verified through the optimizer's
    enumerate_combinations; we don't need a real bridge call to test this.
    """
    import mep_opt.optimizer.smart_search as ss

    # ~22 MSA traffic — falls into the (20, 50] tier
    problem = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0, commercial_vehicles_per_day=3000,
            traffic_growth_rate=0.0, design_life_years=20,
            lane_distribution_factor=1.0, vehicle_damage_factor=1.0,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC": (30, 50), "DBM": (50, 100),
            "WMM": (150, 250), "GSB": (150, 250),
        },
    )
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = ss.SmartPavementSearch(problem)
        combos = opt._enumerate_combinations()
    finally:
        ss.is_bridge_available = orig

    # Every surviving combo must satisfy the > 20 MSA tier:
    #   BC ≥ 40, DBM ≥ 50, BC + DBM ≥ 100
    for c in combos:
        bc, dbm = c[0], c[1]
        assert bc >= 40, f"BC={bc} survived for >20 MSA — should require ≥40"
        assert dbm >= 50, f"DBM={dbm} survived for >20 MSA — should require ≥50"
        assert bc + dbm >= 100, f"BC+DBM={bc+dbm} survived — bundle should ≥100"


def test_traffic_tier_minimums_can_be_disabled():
    """Setting `ignore_minimum_thickness=True` skips the IRC/MoRTH filter."""
    import mep_opt.optimizer.smart_search as ss

    problem = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0, commercial_vehicles_per_day=3000,
            traffic_growth_rate=0.0, design_life_years=20,
            lane_distribution_factor=1.0, vehicle_damage_factor=1.0,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC": (30, 50), "DBM": (50, 100),
            "WMM": (150, 250), "GSB": (150, 250),
        },
        ignore_minimum_thickness=True,
    )
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = ss.SmartPavementSearch(problem)
        combos = opt._enumerate_combinations()
    finally:
        ss.is_bridge_available = orig

    # With the filter off, BC=30 (the lift-schedule minimum) is allowed
    # even though we're in the >20 MSA tier
    assert any(c[0] == 30 for c in combos)


def test_archetype_selection_falls_back_when_no_design_below_ceiling():
    """If every design fails the ceiling, Premium = lowest-CDF on the front."""
    problem = _stub_problem()
    problem.premium_cdf_ceiling = 0.3   # tight ceiling — no design clears it
    import mep_opt.optimizer.smart_search as ss
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        opt = SmartPavementSearch(problem)
    finally:
        ss.is_bridge_available = orig

    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95),
        _result([30, 75, 200, 200], 80e5, 0.60),
        _result([40, 90, 250, 250], 95e5, 0.45),  # lowest CDF — fallback Premium
    ]
    archetypes = opt._select_archetypes(designs)
    labels = {a.performance["strategy"]: a for a in archetypes}
    assert labels["Premium"].cost == 95e5


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
