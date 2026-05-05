"""
Tests for advanced-module input validation: corridor CSV parsing and
strain-field spacing requirements (Issues.md #4 + #5).

These tests are pure-Python and don't require the legacy bridge.
"""

import pytest
from pydantic import ValidationError

from mep_opt.advanced.corridor import parse_corridor_csv
from mep_opt.advanced.strain_field import compute_strain_field


# ----------------------------------------------------------------------
# Issue #4 — corridor CSV column validation
# ----------------------------------------------------------------------

GOOD_CSV = """\
Chainage,Subgrade_CBR,CVPD,VDF,LDF
0+000,8,800,2.5,0.75
0+500,6,700,2.5,0.75
"""


def test_parse_corridor_csv_happy_path():
    """A well-formed CSV produces typed sections."""
    sections = parse_corridor_csv(GOOD_CSV)
    assert len(sections) == 2
    assert sections[0]["chainage"] == "0+000"
    assert sections[0]["cbr"] == 8.0
    assert sections[0]["cvpd"] == 800.0
    assert sections[0]["vdf"] == 2.5
    assert sections[0]["ldf"] == 0.75


def test_parse_corridor_csv_accepts_cbr_alias():
    """The shorter 'CBR' header should be accepted as an alias of 'Subgrade_CBR'."""
    csv_text = "Chainage,CBR,CVPD,VDF,LDF\n0+000,8,800,2.5,0.75\n"
    sections = parse_corridor_csv(csv_text)
    assert sections[0]["cbr"] == 8.0


def test_parse_corridor_csv_case_insensitive_headers():
    """Header matching must be case-insensitive (real-world CSVs vary)."""
    csv_text = "chainage,subgrade_cbr,cvpd,vdf,ldf\n0+000,8,800,2.5,0.75\n"
    sections = parse_corridor_csv(csv_text)
    assert sections[0]["cbr"] == 8.0


def test_parse_corridor_csv_rejects_missing_column():
    """A missing column (the bug Issue #4 was about) must raise — never default silently."""
    csv_text = "Chainage,Subgrade_CBR,VDF,LDF\n0+000,8,2.5,0.75\n"  # no CVPD
    with pytest.raises(ValueError, match="missing required column"):
        parse_corridor_csv(csv_text)


def test_parse_corridor_csv_rejects_misspelled_column():
    """Common typo cases must be flagged, not silently fall back."""
    csv_text = "Chainage,SubgradeCBR,CVPD,VDF,LDF\n0+000,8,800,2.5,0.75\n"
    with pytest.raises(ValueError, match="missing required column"):
        parse_corridor_csv(csv_text)


def test_parse_corridor_csv_rejects_empty_input():
    with pytest.raises(ValueError, match="empty or has no header"):
        parse_corridor_csv("")


def test_parse_corridor_csv_rejects_header_only():
    with pytest.raises(ValueError, match="no data rows"):
        parse_corridor_csv("Chainage,Subgrade_CBR,CVPD,VDF,LDF\n")


def test_parse_corridor_csv_row_with_non_numeric_value():
    """A non-numeric cell points the user at the offending row."""
    csv_text = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n0+000,oops,800,2.5,0.75\n"
    with pytest.raises(ValueError, match="row 2"):
        parse_corridor_csv(csv_text)


def test_parse_corridor_csv_rejects_empty_chainage():
    csv_text = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n,8,800,2.5,0.75\n"
    with pytest.raises(ValueError, match="chainage' is empty"):
        parse_corridor_csv(csv_text)


def test_parse_corridor_csv_rejects_negative_cbr():
    csv_text = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n0+000,-1,800,2.5,0.75\n"
    with pytest.raises(ValueError, match="cbr must be > 0"):
        parse_corridor_csv(csv_text)


def test_parse_corridor_csv_rejects_invalid_ldf():
    """LDF outside (0, 1] is a hard error."""
    csv_text = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n0+000,8,800,2.5,1.5\n"
    with pytest.raises(ValueError, match="ldf must be in"):
        parse_corridor_csv(csv_text)


# ----------------------------------------------------------------------
# Issue #5 — strain field requires explicit spacing for dual-tire loads
# ----------------------------------------------------------------------

_MINIMAL_LAYERS = [
    {"modulus": 1250.0, "poisson": 0.35, "thickness": 40, "name": "BC"},
    {"modulus": 200.0,  "poisson": 0.40, "thickness": 0,  "name": "Subgrade"},
]


def test_compute_strain_field_dual_tire_requires_spacing():
    """Omitting spacing on a dual-tire load must raise, not silently default."""
    with pytest.raises(ValueError, match="requires an explicit 'spacing'"):
        compute_strain_field(
            layers=_MINIMAL_LAYERS,
            load_data={"load": 20000, "pressure": 0.56, "is_dual": True},
            r_steps=2, z_steps=2, r_max=200,
        )


def test_compute_strain_field_dual_tire_rejects_implausible_spacing():
    """A 1 mm or 5000 mm dual spacing is an obvious input error."""
    with pytest.raises(ValueError, match="50–2000 mm"):
        compute_strain_field(
            layers=_MINIMAL_LAYERS,
            load_data={"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 1.0},
            r_steps=2, z_steps=2, r_max=200,
        )
    with pytest.raises(ValueError, match="50–2000 mm"):
        compute_strain_field(
            layers=_MINIMAL_LAYERS,
            load_data={"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 5000.0},
            r_steps=2, z_steps=2, r_max=200,
        )


def test_compute_strain_field_dual_tire_rejects_non_numeric_spacing():
    """A string in 'spacing' must be flagged before reaching the bridge."""
    with pytest.raises(ValueError, match="spacing must be numeric"):
        compute_strain_field(
            layers=_MINIMAL_LAYERS,
            load_data={"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": "wide"},
            r_steps=2, z_steps=2, r_max=200,
        )


# ----------------------------------------------------------------------
# Issue #6 — router-level reliability validation
# ----------------------------------------------------------------------

def test_router_rejects_non_irc_reliability_in_sensitivity_request():
    """SensitivityRequest must reject reliability values outside (80, 90)."""
    from mep_opt.advanced.router import SensitivityRequest, LoadData, LayerData
    layer = LayerData(modulus=1250, poisson=0.35, thickness=40)
    load = LoadData(load=20000, pressure=0.56, is_dual=True, spacing=310)

    # 80 and 90 are accepted
    SensitivityRequest(
        layers=[layer], load=load, eval_points=[],
        cumulative_msa=10.0, mix_modulus=1250, reliability=80,
    )
    SensitivityRequest(
        layers=[layer], load=load, eval_points=[],
        cumulative_msa=10.0, mix_modulus=1250, reliability=90,
    )
    # 95 is not
    with pytest.raises(ValueError, match="reliability must be one of"):
        SensitivityRequest(
            layers=[layer], load=load, eval_points=[],
            cumulative_msa=10.0, mix_modulus=1250, reliability=95,
        )


def test_router_rejects_non_irc_reliability_in_montecarlo_request():
    """MonteCarloRequest must apply the same IRC-compliance check."""
    from mep_opt.advanced.router import MonteCarloRequest, LoadData, LayerData
    layer = LayerData(modulus=1250, poisson=0.35, thickness=40)
    load = LoadData(load=20000, pressure=0.56, is_dual=True, spacing=310)
    with pytest.raises(ValueError, match="reliability must be one of"):
        MonteCarloRequest(
            layers=[layer], load=load, eval_points=[],
            cumulative_msa=10.0, mix_modulus=1250, reliability=99,
        )


def test_router_rejects_non_irc_reliability_in_corridor_request():
    """CorridorRequest must apply the same IRC-compliance check."""
    from mep_opt.advanced.router import CorridorRequest, CorridorConstraint
    constraint = CorridorConstraint(
        layer_type="BC", min_thickness=30, max_thickness=50, E=1250, nu=0.35,
    )
    with pytest.raises(ValueError, match="reliability must be one of"):
        CorridorRequest(
            layer_constraints=[constraint],
            growth_rate=0.05, design_life=20, reliability=98,
        )


def test_router_rejects_invalid_load_data():
    """Invalid load geometry should fail at the API boundary."""
    from mep_opt.advanced.router import LoadData

    with pytest.raises(ValidationError, match="load must be positive"):
        LoadData(load=0, pressure=0.56, is_dual=True, spacing=310)
    with pytest.raises(ValidationError, match="spacing must be between 0 and 2000"):
        LoadData(load=20000, pressure=0.56, is_dual=True, spacing=2500)
    with pytest.raises(ValidationError, match="dual-tire loads require a positive spacing"):
        LoadData(load=20000, pressure=0.56, is_dual=True, spacing=0)


def test_router_rejects_invalid_layer_data():
    """Layer material parameters should be validated before hitting the solver."""
    from mep_opt.advanced.router import LayerData

    with pytest.raises(ValidationError, match="modulus must be positive"):
        LayerData(modulus=0, poisson=0.35, thickness=40)
    with pytest.raises(ValidationError, match="poisson must be in"):
        LayerData(modulus=1250, poisson=0.5, thickness=40)
    with pytest.raises(ValidationError, match="thickness must be non-negative"):
        LayerData(modulus=1250, poisson=0.35, thickness=-1)


def test_router_rejects_invalid_eval_point_data():
    """Negative coordinates are nonsensical for analysis points."""
    from mep_opt.advanced.router import EvalPointData

    with pytest.raises(ValidationError, match="z must be non-negative"):
        EvalPointData(z=-1, r=0)
    with pytest.raises(ValidationError, match="r must be non-negative"):
        EvalPointData(z=10, r=-5)


def test_router_rejects_invalid_corridor_constraint():
    """Corridor layer constraints must remain internally consistent."""
    from mep_opt.advanced.router import CorridorConstraint

    with pytest.raises(ValidationError, match="min_thickness cannot exceed max_thickness"):
        CorridorConstraint(layer_type="BC", min_thickness=60, max_thickness=50, E=1250, nu=0.35)
    with pytest.raises(ValidationError, match="E must be positive"):
        CorridorConstraint(layer_type="BC", min_thickness=30, max_thickness=50, E=0, nu=0.35)


# ----------------------------------------------------------------------
# Issue #42 — compute_reserve must return JSON-safe (finite) numbers
# ----------------------------------------------------------------------

def test_compute_reserve_returns_finite_numbers_for_zero_strain():
    """Vanishingly small strain → infinite capacity → must clamp to a
    large finite number so the API response serialises cleanly."""
    import math
    from mep_opt.advanced.reserve import compute_reserve

    result = compute_reserve(
        eps_t=0.0,        # → Nf = inf
        eps_v=0.0,        # → NR = inf
        mix_modulus=1250.0,
        design_msa=10.0,
        reliability=80,
    )
    # Every numeric field must be a finite number, not Infinity / NaN
    for key in ("design_msa", "intercept_msa", "reserve_percent", "Nf_msa", "NR_msa"):
        assert math.isfinite(result[key]), (
            f"{key} = {result[key]!r} must be finite for JSON safety"
        )
    # The unbounded flag tells the UI it's an unbounded case so it can
    # render "Excellent (capacity ≫ design)" instead of a giant number.
    assert result["is_unbounded"] is True


def test_compute_reserve_normal_case_unflagged():
    """Bounded strain inputs must return is_unbounded=False."""
    from mep_opt.advanced.reserve import compute_reserve
    result = compute_reserve(
        eps_t=200e-6,
        eps_v=400e-6,
        mix_modulus=1250.0,
        design_msa=10.0,
        reliability=80,
    )
    assert result["is_unbounded"] is False


def test_compute_reserve_zero_design_traffic_is_unbounded():
    """Zero design MSA → reserve is unbounded, must still serialise cleanly."""
    import math
    from mep_opt.advanced.reserve import compute_reserve
    result = compute_reserve(
        eps_t=200e-6, eps_v=400e-6, mix_modulus=1250.0,
        design_msa=0.0, reliability=80,
    )
    assert math.isfinite(result["reserve_percent"])
    assert result["is_unbounded"] is True
