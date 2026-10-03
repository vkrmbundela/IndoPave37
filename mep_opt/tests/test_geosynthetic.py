"""Tests for IRC:SP:59 geosynthetic MIF reinforcement (Saride et al. 2022 table,
capped at the IRC:SP:59-2019 §3.1.3 design maximum of 2.0)."""

import pytest

from mep_opt.solver.geosynthetic import (
    get_mif, research_mif, MIF_TABLE, list_geogrid_types, NONE_OPTION, SP59_GEOGRID_MIF_MAX,
)
from mep_opt.solver.irc37 import build_layer_stack, SubgradeInput, BituminousLayerInput
from mep_opt.solver.solver_facade import run_solver, set_solver_backend, SolverBackend


# --- MIF lookup ---------------------------------------------------------------

def test_research_mif_exact_table_values():
    # The research table itself is reproduced exactly (no cap).
    assert research_mif(10, "PP30") == 3.13
    assert research_mif(30, "PET30") == 2.06
    assert research_mif(50, "PET60") == 2.00
    assert research_mif(70, "PP30") == 1.50


def test_design_mif_capped_at_sp59_maximum():
    # IRC:SP:59-2019 §3.1.3: geogrid MIF for design shall be 1.2 to 2.0.
    assert SP59_GEOGRID_MIF_MAX == 2.0
    assert get_mif(10, "PP30") == 2.0      # research 3.13
    assert get_mif(10, "PET30") == 2.0     # research 3.50
    assert get_mif(30, "PET60") == 2.0     # research 2.25
    assert get_mif(50, "PP30") == 1.60     # below the cap: unchanged
    for g in MIF_TABLE:
        for mrs in (1, 5, 10, 20, 30, 45, 60, 80, 100, 150):
            assert 1.0 <= get_mif(mrs, g) <= 2.0


def test_mif_linear_interpolation():
    # PP30 between Mrs=30 (1.88) and Mrs=50 (1.60) at Mrs=40 -> midpoint 1.74.
    assert get_mif(40, "PP30") == pytest.approx(1.74, abs=1e-9)


def test_mif_outside_table_is_conservative():
    # Below the table: hold the first value (MIF grows as the subgrade weakens).
    assert research_mif(5, "PP30") == 3.13
    # Above the table: MIF keeps FALLING along the last segment (holding it
    # flat would over-state the benefit on stiff subgrades), floored at 1.0.
    assert research_mif(100, "PP30") == pytest.approx(1.50 - 0.005 * 30)   # 1.35
    assert research_mif(100, "PET30") == pytest.approx(1.80 - 0.013 * 50)  # 1.15
    assert research_mif(1000, "PET30") == 1.0
    assert get_mif(100, "PP30") < get_mif(70, "PP30")


def test_mif_none_and_unknown_return_unity():
    assert get_mif(30, None) == 1.0
    assert get_mif(30, NONE_OPTION) == 1.0
    assert get_mif(30, "NOPE") == 1.0


def test_mif_monotonic_with_subgrade_and_geogrid():
    # Weaker subgrade → larger uplift; stronger geogrid → larger uplift.
    assert get_mif(10, "PP30") > get_mif(50, "PP30")
    assert get_mif(50, "PET60") > get_mif(50, "PP30")


def test_geogrid_types_listing_includes_none_and_all_grids():
    ids = {g["id"] for g in list_geogrid_types()}
    assert NONE_OPTION in ids
    assert set(MIF_TABLE).issubset(ids)


# --- Effect on the layer stack & solver --------------------------------------

def _stack(geogrid, force_unit_mif=False, monkeypatch=None):
    sub = SubgradeInput(cbr=8.0)
    bit = [BituminousLayerInput("BC", 40, 1250, 0.35),
           BituminousLayerInput("DBM", 60, 1250, 0.35)]
    gran = [
        {"thickness": 250, "layer_type": "WMM", **({"geogrid": geogrid} if geogrid else {})},
        {"thickness": 200, "layer_type": "GSB"},
    ]
    if force_unit_mif:
        import mep_opt.solver.geosynthetic as gs
        monkeypatch.setattr(gs, "get_mif", lambda mrs, g: 1.0)
    return build_layer_stack(sub, gran, bit)


LOAD = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
# Bituminous bottom (100 mm) and TOP OF SUBGRADE (100 + 250 + 200 = 550 mm).
PTS = [{"z": 99.9, "r": 0}, {"z": 99.9, "r": 155}, {"z": 550.1, "r": 0}, {"z": 550.1, "r": 155}]


def _critical(stack):
    set_solver_backend(SolverBackend.NATIVE)
    res = run_solver(stack, LOAD, PTS)
    eps_t = max(max(r["eps_t"], r["eps_r"]) for r in res[:2])
    eps_v = max(abs(r["eps_z"]) for r in res[2:])
    return eps_t, eps_v


def test_geogrid_uplifts_base_modulus():
    plain = _stack(None)
    grid = _stack("PET60")
    # Plain collapses to a single composite granular row; the geogrid breaks
    # the collapse and uplifts the reinforced base — so the max granular
    # modulus must be higher with the grid.
    plain_max_gran = max(l["modulus"] for l in plain[2:-1])
    grid_max_gran = max(l["modulus"] for l in grid[2:-1])
    assert grid_max_gran > plain_max_gran


def test_geogrid_reduces_critical_strains():
    plain_t, plain_v = _critical(_stack(None))
    grid_t, grid_v = _critical(_stack("PET60"))
    assert grid_t < plain_t   # fatigue strain drops
    assert grid_v < plain_v   # rutting strain at the TOP OF THE SUBGRADE drops


def test_reinforced_base_rests_on_effective_modulus(monkeypatch):
    """
    IRC:37-2018 §8.1: the un-reinforced base modulus (before the MIF) uses
    Eq. 7.1 on the EFFECTIVE modulus of the GSB + subgrade system — not the
    GSB layer's own modulus.
    """
    from mep_opt.solver.irc37 import effective_modulus
    stack = _stack("PET60", force_unit_mif=True, monkeypatch=monkeypatch)
    sub = SubgradeInput(cbr=8.0).modulus
    e_gsb = 0.2 * 200 ** 0.45 * sub
    e_eff = effective_modulus([
        {"modulus": e_gsb, "poisson": 0.35, "thickness": 200},
        {"modulus": sub, "poisson": 0.35, "thickness": 0},
    ])
    assert sub < e_eff < e_gsb
    assert stack[3]["modulus"] == pytest.approx(e_gsb)
    assert stack[2]["modulus"] == pytest.approx(0.2 * 250 ** 0.45 * e_eff)


def test_zero_benefit_geogrid_matches_irc_composite(monkeypatch):
    """
    With MIF forced to 1.0 the separated (reinforcement) model must stay close
    to the IRC §7.2.3 composite: the geogrid benefit must come from the MIF,
    not from switching idealisations (previously a MIF of 1.0 already cut the
    fatigue strain by ~24%).
    """
    comp_t, comp_v = _critical(_stack(None))
    unit_t, unit_v = _critical(_stack("PET60", force_unit_mif=True, monkeypatch=monkeypatch))
    assert unit_t == pytest.approx(comp_t, rel=0.08)
    assert unit_v == pytest.approx(comp_v, rel=0.02)


def test_geogrid_rejected_on_non_granular_layer():
    sub = SubgradeInput(cbr=8.0)
    with pytest.raises(ValueError, match="Geogrid"):
        build_layer_stack(sub, [
            {"thickness": 150, "layer_type": "CTB", "E": 5000, "nu": 0.25, "geogrid": "PP30"},
            {"thickness": 200, "layer_type": "GSB"},
        ], [])
