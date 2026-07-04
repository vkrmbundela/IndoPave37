import pytest
from mep_opt.solver.irc37 import AxleLoadGroup, ctb_fatigue_life, check_ctb_adequacy

def test_ctb_low_stress_is_finite_not_capped():
    # The low-SR branch is no longer fabricated as infinite life.
    # Stress remains finite and should still produce a large but bounded life.
    life = ctb_fatigue_life(0.5, 1.4)
    assert life != float('inf')
    assert life > 1e6

def test_ctb_finite_life():
    # SR = 1.0 (sigma_t = 1.4). N = 10^((0.972 - 1.0)/0.0825) = 10^(-0.339..) = 0.45
    life = ctb_fatigue_life(1.4, 1.4)
    assert life < 1.0  # Fails almost instantly if SR = 1.0

    # SR = 0.8. N = 10^((0.972-0.8)/0.0825) = 10^(2.08) = roughly 121
    life = ctb_fatigue_life(1.4 * 0.8, 1.4)
    assert 100 < life < 150

def test_ctb_spectrum_adequacy():
    spectrum = [
        AxleLoadGroup("single", 100.0, 50.0),
        AxleLoadGroup("tandem", 180.0, 10.0),
        AxleLoadGroup("tridem", 240.0, 0.0)
    ]
    
    # 0.5 -> SR=0.35 -> inf allowable -> damage = 0
    # 1.12 -> SR=0.8 -> N ~ 121 allowable. applied=10. damage = 10/121 = 0.08
    # whatever -> applied=0 -> damage=0
    computed = [0.5, 1.12, 1.2]
    
    res = check_ctb_adequacy(spectrum, computed, 1.4)
    assert res['ctb_adequate'] == True
    assert 0.08 < res['CDF_ctb'] < 0.09
    
def test_ctb_spectrum_failure():
    spectrum = [
        AxleLoadGroup("single", 100.0, 500.0), # apply 500 times
    ]
    # SR=0.8. N_allowable ~ 121. applied = 500. damage = 500/121 > 1.0
    computed = [1.12]
    
    res = check_ctb_adequacy(spectrum, computed, 1.4)
    assert res['ctb_adequate'] == False
    assert res['CDF_ctb'] > 1.0


# ---------------------------------------------------------------------------
# Strain-based CTB fatigue (IRC:37-2018 Eq. 3.5) — added in the July-2026
# audit fixes. N = RF * [(113000/E^0.804 + 191)/eps_t_micro]^12
# ---------------------------------------------------------------------------

from mep_opt.solver.irc37 import ctb_fatigue_life_strain, ReliabilityLevel


def test_ctb_strain_life_matches_hand_calc():
    """E=5000 MPa, eps_t=53.5 microstrain, R90 (RF=1) -> ~1.48e9 reps.

    Hand calculation: 5000^0.804 = 942.2; 113000/942.2 = 119.9;
    (119.9+191)/53.5 = 5.811; 5.811^12 = 1.48e9.
    """
    n = ctb_fatigue_life_strain(53.5e-6, 5000.0, ReliabilityLevel.R90)
    assert n == pytest.approx(1.48e9, rel=0.02)


def test_ctb_strain_life_rf_doubles_at_r80():
    """RF = 2 for 80% reliability -> exactly twice the R90 life."""
    n90 = ctb_fatigue_life_strain(60e-6, 5000.0, ReliabilityLevel.R90)
    n80 = ctb_fatigue_life_strain(60e-6, 5000.0, ReliabilityLevel.R80)
    assert n80 == pytest.approx(2.0 * n90, rel=1e-9)


def test_ctb_strain_life_guards():
    assert ctb_fatigue_life_strain(0.0, 5000.0) == float('inf')
    with pytest.raises(ValueError):
        ctb_fatigue_life_strain(60e-6, 0.0)


def test_optimizer_ctb_no_spectrum_uses_strain_criterion():
    """Without an axle spectrum the CTB gate must be the Eq. 3.5 strain check
    (the old fallback applied the stress-ratio equation to the full design
    traffic at the standard axle — a construct in neither IRC method)."""
    from mep_opt.optimizer.smart_search import SmartPavementSearch
    from mep_opt.optimizer.problem import OptimizationProblem
    from mep_opt.solver.irc37 import TrafficInput, SubgradeInput

    problem = OptimizationProblem(
        traffic=TrafficInput(initial_aadt=0, commercial_vehicles_per_day=3000,
                             traffic_growth_rate=0.05, design_life_years=20),
        subgrade=SubgradeInput(cbr=8.0),
        reliability=ReliabilityLevel.R90,
        layer_types=["BC", "DBM", "WMM", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60), "WMM": (150, 150),
                          "CTB": (150, 150), "GSB": (150, 150)},
    )
    opt = SmartPavementSearch(problem)

    def fake_bridge(stack, load_cfg, eval_points):
        row = {"sigma_t": 0.30, "eps_t": 50e-6, "eps_r": 40e-6,
               "eps_z": 300e-6, "sigma_z": 0.0, "sigma_r": 0.0,
               "tau_rz": 0.0, "disp_z": 0.0, "disp_r": 0.0}
        return [dict(row, z=pt["z"], r=pt["r"]) for pt in eval_points]

    opt._bridge_call = fake_bridge  # type: ignore[method-assign]
    result = opt._evaluate([40.0, 60.0, 150.0, 150.0, 150.0])

    assert result["CDF_ctb_strain"] is not None
    # No spectrum: the governing CTB CDF IS the strain-based CDF.
    assert result["CDF_ctb"] == pytest.approx(result["CDF_ctb_strain"])
    assert result["ctb_details"] is None
    assert result["eps_t_ctb"] == pytest.approx(50e-6)
    # Cross-check the number: msa*1e6 / Eq3.5 life at E=5000, 50 ue, RF=1.
    msa = problem.traffic.cumulative_msa()
    n_allow = ctb_fatigue_life_strain(50e-6, 5000.0, ReliabilityLevel.R90)
    assert result["CDF_ctb"] == pytest.approx(msa * 1e6 / n_allow, rel=1e-6)
    # Advisory: the run-level warnings must tell the user the spectrum
    # (stress-ratio) check was not performed.
    warnings = opt._build_warnings()
    assert any("Eq. 3.6" in w and "spectrum" in w for w in warnings)


def test_optimizer_ctb_with_spectrum_governs_on_worse_of_two_checks():
    """With a spectrum BOTH IRC checks run; the reported CDF is the max."""
    from mep_opt.optimizer.smart_search import SmartPavementSearch
    from mep_opt.optimizer.problem import OptimizationProblem
    from mep_opt.solver.irc37 import TrafficInput, SubgradeInput

    problem = OptimizationProblem(
        traffic=TrafficInput(initial_aadt=0, commercial_vehicles_per_day=3000,
                             traffic_growth_rate=0.05, design_life_years=20),
        subgrade=SubgradeInput(cbr=8.0),
        reliability=ReliabilityLevel.R90,
        layer_types=["BC", "DBM", "WMM", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60), "WMM": (150, 150),
                          "CTB": (150, 150), "GSB": (150, 150)},
        ctb_axle_spectrum=[
            AxleLoadGroup("single", 20.0, 1000.0),
            AxleLoadGroup("tandem", 40.0, 500.0),
        ],
    )
    opt = SmartPavementSearch(problem)

    def fake_bridge(stack, load_cfg, eval_points):
        row = {"sigma_t": 0.30, "eps_t": 50e-6, "eps_r": 40e-6,
               "eps_z": 300e-6, "sigma_z": 0.0, "sigma_r": 0.0,
               "tau_rz": 0.0, "disp_z": 0.0, "disp_r": 0.0}
        return [dict(row, z=pt["z"], r=pt["r"]) for pt in eval_points]

    opt._bridge_call = fake_bridge  # type: ignore[method-assign]
    result = opt._evaluate([40.0, 60.0, 150.0, 150.0, 150.0])

    assert result["ctb_details"] is not None            # spectrum CFD ran
    assert result["CDF_ctb_strain"] is not None         # Eq 3.5 ran too
    assert result["CDF_ctb"] == pytest.approx(
        max(result["CDF_ctb_strain"], result["ctb_details"]["CDF_ctb"])
    )
