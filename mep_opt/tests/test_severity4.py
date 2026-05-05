"""
Tests for Severity-4 quality / robustness improvements.

Most are pure-Python (no bridge required); the one parallel test
exercises the worker-pool code path with mocked bridge calls so it
runs in milliseconds.
"""

import threading
import pytest

import mep_opt.optimizer.smart_search as ss
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput
from mep_opt.solver.legacy_bridge import (
    set_bridge_cache_size,
    get_bridge_cache_stats,
    clear_bridge_cache,
)


# ---------------------------------------------------------------------- helpers

def _result(thicknesses, cost, cdf, cdf_rut=0.0, ctb=None, co2=None):
    return {
        "thicknesses": list(thicknesses),
        "total_thickness": sum(thicknesses),
        "cost_per_km": cost,
        "co2_per_km": co2 if co2 is not None else cost / 100.0,
        "CDF_fatigue": cdf,
        "CDF_rutting": cdf_rut,
        "CDF_ctb": ctb,
        "overall_adequate": True,
        "governing_mode": "fatigue" if cdf >= cdf_rut else "rutting",
    }


def _stub(material_rates=None, **kwargs):
    """Build a problem and bypass the bridge availability check."""
    p = OptimizationProblem(
        traffic=TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=2000,
            traffic_growth_rate=0.05,
            design_life_years=20,
        ),
        subgrade=SubgradeInput(cbr=8.0),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={
            "BC": (30, 50), "DBM": (50, 100),
            "WMM": (150, 250), "GSB": (150, 250),
        },
        material_rates=material_rates,
        **kwargs,
    )
    orig = ss.is_bridge_available
    ss.is_bridge_available = lambda: True
    try:
        return SmartPavementSearch(p)
    finally:
        ss.is_bridge_available = orig


# ---------------------------------------------------------------------- #4.1
# Local monotonicity probing

def test_monotonicity_probe_flags_non_monotonic_neighbour():
    """If a thinner neighbour has a *lower* CDF than the chosen Economy,
    that's a non-monotonicity flag worth surfacing."""
    opt = _stub()
    # Anchor design with one thinner neighbour that mysteriously has
    # *lower* CDF — this is the surface-pathology we want to flag.
    anchor = _result([40, 75, 200, 200], 50e5, 0.50)
    neighbour = _result([30, 75, 200, 200], 45e5, 0.40)  # thinner BC, lower CDF
    other = _result([50, 100, 250, 250], 110e5, 0.20)
    flags = opt._detect_non_monotonicity(anchor, [anchor, neighbour, other])
    assert len(flags) == 1
    assert flags[0]["layer_index"] == 0  # BC
    assert flags[0]["thickness_drop_mm"] == 10
    assert flags[0]["anchor_cdf"] == 0.50
    assert flags[0]["neighbour_cdf"] == 0.40


def test_monotonicity_probe_silent_when_monotone():
    opt = _stub()
    # Surface is well-behaved: thinner → higher CDF.
    anchor = _result([40, 75, 200, 200], 50e5, 0.40)
    neighbour = _result([30, 75, 200, 200], 45e5, 0.55)  # thinner → higher CDF (good)
    flags = opt._detect_non_monotonicity(anchor, [anchor, neighbour])
    assert flags == []


# ---------------------------------------------------------------------- #4.2
# Premium tiebreaker (cost-primary, CDF tiebreaker)

def test_premium_picks_cheapest_under_ceiling_not_lowest_cdf():
    opt = _stub()
    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95),    # too high CDF
        _result([30, 75, 200, 200], 80e5, 0.40),    # under ceiling, cheapest
        _result([40, 90, 250, 250], 95e5, 0.25),    # under ceiling, more expensive
        _result([50, 100, 250, 250], 110e5, 0.15),  # absolute lowest CDF — but NOT Premium
    ]
    archetypes = opt._select_archetypes(designs)
    by_label = {a.performance["strategy"]: a for a in archetypes}
    assert by_label["Premium"].cost == 80e5


def test_premium_breaks_cost_ties_by_lower_cdf():
    """If two designs sit at the same cost, the one with lower CDF wins."""
    opt = _stub()
    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95),  # Economy
        # Both at 80e5 cost, but [30, 90, 200, 200] has lower CDF
        _result([30, 75, 200, 200], 80e5, 0.55),
        _result([30, 90, 200, 200], 80e5, 0.40),
    ]
    archetypes = opt._select_archetypes(designs)
    by_label = {a.performance["strategy"]: a for a in archetypes}
    # Premium should be the 0.40-CDF design (CDF tiebreaker on equal cost)
    assert by_label["Premium"].performance["CDF_fatigue"] == 0.40


# ---------------------------------------------------------------------- #4.3
# Infeasibility messaging

def test_infeasibility_message_explains_what_to_relax():
    """When no design is adequate, the result carries an actionable hint."""
    opt = _stub()
    # Manually populate the diagnostic with a near-passing design.
    opt._all_evaluated = [
        {"thicknesses": [30, 50, 150, 150], "CDF_fatigue": 1.4,
         "CDF_rutting": 0.6, "CDF_ctb": None, "governing_mode": "fatigue"},
    ]
    diag = opt._closest_to_passing_diagnostic()
    assert diag is not None
    assert diag["max_cdf"] == 1.4
    assert diag["governing_mode"] == "fatigue"


def test_closest_to_passing_returns_none_when_no_evals():
    opt = _stub()
    opt._all_evaluated = []
    assert opt._closest_to_passing_diagnostic() is None


# ---------------------------------------------------------------------- #4.4
# Bridge result cache

def test_bridge_cache_disabled_by_default():
    clear_bridge_cache()
    set_bridge_cache_size(0)
    stats = get_bridge_cache_stats()
    assert stats["max"] == 0
    assert stats["size"] == 0


def test_bridge_cache_lru_eviction():
    """Filling beyond capacity must drop the oldest entries."""
    from mep_opt.solver.iitpave_bridge import _cache_get, _cache_put
    clear_bridge_cache()
    set_bridge_cache_size(3)
    for i in range(5):
        _cache_put((i,), [{"v": i}])
    stats = get_bridge_cache_stats()
    assert stats["size"] == 3
    # Oldest two should have been evicted
    assert _cache_get((0,)) is None
    assert _cache_get((1,)) is None
    # Most recent three remain
    assert _cache_get((2,)) is not None
    assert _cache_get((3,)) is not None
    assert _cache_get((4,)) is not None


def test_bridge_cache_returns_deep_copies():
    """A cache hit must return a copy so callers can mutate freely."""
    from mep_opt.solver.iitpave_bridge import _cache_get, _cache_put
    clear_bridge_cache()
    set_bridge_cache_size(8)
    _cache_put(("k",), [{"eps_t": 1e-4, "extras": [1, 2, 3]}])
    a = _cache_get(("k",))
    b = _cache_get(("k",))
    assert a is not b
    a[0]["extras"].append(99)
    # Mutation in `a` must NOT leak into the cache
    c = _cache_get(("k",))
    assert c[0]["extras"] == [1, 2, 3]
    clear_bridge_cache()
    set_bridge_cache_size(0)


def test_bridge_cache_hit_miss_counters():
    from mep_opt.solver.iitpave_bridge import _cache_get, _cache_put
    clear_bridge_cache()
    set_bridge_cache_size(8)
    assert get_bridge_cache_stats()["hits"] == 0
    _cache_put(("a",), [1])
    _cache_get(("a",))   # hit
    _cache_get(("a",))   # hit
    _cache_get(("z",))   # miss
    stats = get_bridge_cache_stats()
    assert stats["hits"] == 2
    assert stats["misses"] >= 1
    clear_bridge_cache()
    set_bridge_cache_size(0)


# ---------------------------------------------------------------------- #4.5
# Parallel worker pool — exercise the routing without a real bridge call

def test_bridge_call_routes_through_thread_local_dir():
    """When `_tls.worker_dir` is set, _bridge_call uses _run_bridge_in_dir."""
    opt = _stub()
    captured = {}

    # Monkey-patch _run_bridge_in_dir to capture the work_dir we routed through
    import mep_opt.solver.iitpave_bridge as ip
    real = ip._run_bridge_in_dir
    def fake_bridge_in_dir(stack, load, points, work_dir, timeout):
        captured["work_dir"] = work_dir
        captured["stack"] = stack
        return [{"eps_t": 1e-4, "eps_r": 1e-5, "eps_z": 5e-4,
                 "sigma_t": 0.0, "sigma_r": 0.0, "sigma_z": 0.0,
                 "tau_rz": 0.0, "disp_z": 0.0,
                 "z": 39.9, "r": 0}]
    ip._run_bridge_in_dir = fake_bridge_in_dir
    try:
        opt._tls.worker_dir = "/tmp/fake_worker_42"
        result = opt._bridge_call(
            [{"modulus": 1250, "poisson": 0.35, "thickness": 40},
             {"modulus": 200, "poisson": 0.40, "thickness": 0}],
            {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
            [{"z": 39.9, "r": 0}],
        )
    finally:
        ip._run_bridge_in_dir = real
        opt._tls.worker_dir = None

    assert captured["work_dir"] == "/tmp/fake_worker_42"
    assert result[0]["eps_t"] == 1e-4


# ---------------------------------------------------------------------- #4.6
# Carbon archetype

def test_carbon_archetype_added_only_when_flag_set():
    opt_off = _stub(include_carbon_archetype=False)
    opt_on = _stub(include_carbon_archetype=True)
    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95, co2=80e3),     # high cost-eff but middling CO2
        _result([30, 75, 200, 200], 80e5, 0.40, co2=70e3),
        _result([40, 90, 250, 250], 95e5, 0.25, co2=40e3),     # lowest CO2
    ]
    arch_off = opt_off._select_archetypes(designs)
    arch_on = opt_on._select_archetypes(designs)
    labels_off = {a.performance["strategy"] for a in arch_off}
    labels_on = {a.performance["strategy"] for a in arch_on}
    assert "Carbon" not in labels_off
    assert "Carbon" in labels_on


def test_carbon_archetype_skipped_when_duplicates_existing():
    """If the lowest-CO2 design is already Economy, don't emit duplicate."""
    opt = _stub(include_carbon_archetype=True)
    # Cheapest AND lowest CO2 are the same design
    designs = [
        _result([30, 50, 150, 150], 50e5, 0.95, co2=30e3),  # Economy AND lowest CO2
        _result([30, 75, 200, 200], 80e5, 0.40, co2=70e3),
        _result([40, 90, 250, 250], 95e5, 0.25, co2=80e3),
    ]
    archetypes = opt._select_archetypes(designs)
    labels = {a.performance["strategy"] for a in archetypes}
    # Carbon is not added when it duplicates Economy
    assert "Carbon" not in labels


# ---------------------------------------------------------------------- #4.7
# Determinism — repeated calls produce identical front

def test_pareto_front_is_deterministic():
    """Two identical inputs must produce identical fronts (no set-iter leak)."""
    designs_a = [_result([30, 50, 150, 150], 50e5, 0.95),
                 _result([40, 90, 250, 250], 95e5, 0.25),
                 _result([30, 75, 200, 200], 80e5, 0.40)]
    designs_b = list(designs_a)  # same data, fresh list
    front_a = SmartPavementSearch._pareto_front(designs_a)
    front_b = SmartPavementSearch._pareto_front(designs_b)
    assert [d["thicknesses"] for d in front_a] == [d["thicknesses"] for d in front_b]
