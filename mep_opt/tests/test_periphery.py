"""
Regression tests for the peripheral modules audited in the May-2026 round:
SP:72 classification, cost/CO2 rates, the dual-wheel default, and the PDF report.
"""

import pytest

from mep_opt.solver import sp72
from mep_opt.cost import DEFAULT_MATERIAL_RATES, estimate_cost, LayerCostSpec
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput


# ---------------------------------------------------------------------------
# SP:72 subgrade classification — gap/monotonicity bug
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cbr,expected", [
    (1.5, "S1"), (2.0, "S1"), (2.5, "S1"),    # very poor (the old bug -> S5)
    (3.0, "S2"), (4.0, "S2"), (4.5, "S2"),    # poor
    (5.0, "S3"), (6.0, "S3"), (6.5, "S3"),    # fair
    (7.0, "S4"), (9.0, "S4"), (9.5, "S4"),    # good
    (10.0, "S5"), (15.0, "S5"), (25.0, "S5"), # very good (+ clamp high)
])
def test_sp72_subgrade_class_gap_free(cbr, expected):
    """Fractional CBR in a band gap must NOT fall through to S5 'Very Good'."""
    label, _ = sp72.classify_subgrade(cbr)
    assert label == expected, f"CBR {cbr}% classified {label}, expected {expected}"


def test_sp72_subgrade_class_monotonic():
    """Higher CBR may never map to a worse (lower) class."""
    rank = {"S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5}
    prev = 0
    for cbr in [1, 2, 2.5, 3, 4, 4.5, 5, 6, 6.5, 7, 8, 9, 9.5, 10, 12, 15, 20]:
        r = rank[sp72.classify_subgrade(cbr)[0]]
        assert r >= prev, f"non-monotonic subgrade class at CBR {cbr}%"
        prev = r


# ---------------------------------------------------------------------------
# Cost / CO2 — CTSB & CRL must have real rates, not the generic fallback
# ---------------------------------------------------------------------------

def test_ctsb_crl_have_dedicated_cost_rates():
    assert "CTSB" in DEFAULT_MATERIAL_RATES, "CTSB missing from cost DB"
    assert "CRL" in DEFAULT_MATERIAL_RATES, "CRL missing from cost DB"
    res = estimate_cost([LayerCostSpec("CTSB", 200), LayerCostSpec("CRL", 100)])
    by_type = {b["type"]: b for b in res.layer_breakdown}
    # Not the generic 5000 INR / 100 kg fallback.
    assert by_type["CTSB"]["cost_rate"] == 3000
    assert by_type["CRL"]["cost_rate"] == 2800
    assert by_type["CTSB"]["co2_rate"] == 90


# ---------------------------------------------------------------------------
# Corridor batch — real IRC moduli, not placeholders
# ---------------------------------------------------------------------------

def test_corridor_uses_irc_moduli_not_placeholders():
    """A corridor section must use the real IRC bituminous modulus (2000 MPa,
    not the old 1250 placeholder) and derive granular modulus from Eq. 7.1
    (E left None) rather than a flat value."""
    from mep_opt.advanced.corridor import _run_single_section
    from mep_opt.solver.materials import get_modulus
    bc_e = get_modulus("BC", temperature=35.0)
    assert bc_e == 2000.0     # IRC:37 Table 9.2 VG30 @ 35C, not the 1250 placeholder
    constraints = [
        {"layer_type": "BC", "min_thickness": 40, "max_thickness": 50, "fixed_thickness": 40,
         "E": bc_e, "nu": 0.35, "is_fixed": True},
        {"layer_type": "DBM", "min_thickness": 50, "max_thickness": 150,
         "E": get_modulus("DBM", temperature=35.0), "nu": 0.35, "is_fixed": False},
        {"layer_type": "WMM", "min_thickness": 150, "max_thickness": 300,
         "E": None, "nu": 0.35, "is_fixed": False},   # granular E via Eq. 7.1
        {"layer_type": "GSB", "min_thickness": 150, "max_thickness": 300,
         "E": None, "nu": 0.35, "is_fixed": False},
    ]
    sec = {"chainage": "0+000", "cbr": 8.0, "cvpd": 800.0, "vdf": 2.5, "ldf": 0.75}
    r = _run_single_section(sec, constraints, growth_rate=0.05, design_life=15, reliability=80)
    assert r["status"] == "ok", f"corridor section failed: {r['status']}"
    assert len(r["thicknesses"]) == 4 and r["total_thickness"] > 0
    assert r["cdf_f"] <= 1.0 and r["cdf_r"] <= 1.0


# ---------------------------------------------------------------------------
# Dual-wheel default — protects the corridor batch & direct library callers
# ---------------------------------------------------------------------------

def test_optimization_problem_defaults_to_dual_wheel():
    prob = OptimizationProblem(
        traffic=TrafficInput(initial_aadt=0, commercial_vehicles_per_day=300,
                             traffic_growth_rate=0.05, design_life_years=15),
        subgrade=SubgradeInput(cbr=8),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60),
                          "WMM": (250, 250), "GSB": (200, 200)},
    )
    assert prob.wheel_type == "Dual", "IRC standard axle is dual-wheel"


# ---------------------------------------------------------------------------
# PDF report — must not crash on null cost/CO2 (toggles off)
# ---------------------------------------------------------------------------

def test_pdf_report_survives_null_cost_and_co2():
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from mep_opt.web.pdf_report import generate_report
    sol = {
        "optimal_layers": [{"type": "BC", "thickness": 40},
                           {"type": "DBM", "thickness": 100},
                           {"type": "WMM", "thickness": 250},
                           {"type": "GSB", "thickness": 200}],
        "total_thickness": 590,
        "cost": None,   # optimize_by_cost off -> API sends null
        "co2": None,    # optimize_by_co2 off
        "details": {"eps_t": 1.46e-4, "eps_v": 2.4e-4, "Nf": 2e8, "NR": 3e8,
                    "CDF_fatigue": 0.5, "CDF_rutting": 0.4, "msa": 50.0,
                    "governing_mode": "fatigue", "overall_adequate": True},
    }
    pdf = generate_report(
        project_name="Null-Cost Test",
        traffic_params={"cvpd": 2000, "growth_rate": 5, "vdf": 2.5, "design_life": 15},
        subgrade_cbr=8.0,
        selected_solution=sol,
        adequate_designs=[sol],
    )
    assert isinstance(pdf, (bytes, bytearray)) and pdf[:4] == b"%PDF"


def test_pdf_report_co2_rendered_in_tonnes_and_branded():
    """End-to-end: CO2 (kg/km) renders as tonnes (40.0, not 40,000), the report
    carries the IndoPave-37 brand, and the IRC:37 compliance verdict appears."""
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO
    from mep_opt.web.pdf_report import generate_report
    sol = {
        "optimal_layers": [{"type": "BC", "thickness": 40},
                           {"type": "DBM", "thickness": 100},
                           {"type": "WMM", "thickness": 250}],
        "total_thickness": 390, "cost": 1_750_000, "co2": 40_000.0,
        "details": {"eps_t": 1.46e-4, "eps_v": 2.4e-4, "Nf": 2e8, "NR": 3e8,
                    "CDF_fatigue": 0.5, "CDF_rutting": 0.4, "CDF_ctb": None,
                    "sigma_t_ctb": None, "msa": 10.0, "strategy": "Economy",
                    "governing_mode": "fatigue", "overall_adequate": True,
                    "layers": [{"id": 1, "name": "BC", "thickness": 40, "modulus": 2000},
                               {"id": 2, "name": "DBM", "thickness": 100, "modulus": 2000},
                               {"id": 3, "name": "WMM", "thickness": 250, "modulus": 250},
                               {"id": 4, "name": "Subgrade", "thickness": 0, "modulus": 65}]},
    }
    pdf = generate_report("Unit Test", {"cvpd": 100, "growth_rate": 0.05,
                          "vdf": 2.5, "design_life": 15}, 8.0, sol, [sol])
    assert pdf[:4] == b"%PDF"
    text = "".join((pg.extract_text() or "") for pg in pypdf.PdfReader(BytesIO(pdf)).pages)
    assert "IndoPave-37" in text                 # branding present
    assert "40.0" in text and "40,000" not in text  # CO2 in tonnes, not kg
    assert "COMPLIANT" in text                   # IRC:37 verdict rendered
