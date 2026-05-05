"""
Unit tests for the role-aware strain extraction helper used by the
sensitivity and Monte Carlo modules. These tests are pure-Python
(no bridge required) and target Issue #6 from Issues.md.
"""

import pytest

from mep_opt.advanced._strain_utils import extract_design_strains


def _row(eps_t=0.0, eps_r=0.0, eps_z=0.0):
    """Build a minimal bridge result row."""
    return {"eps_t": eps_t, "eps_r": eps_r, "eps_z": eps_z}


# --- Default convention: 4 points → first 2 = bit, next 2 = sub ---

def test_default_convention_4_points():
    """With 4 results the helper assumes [0,1]=bit and [2,3]=sub."""
    results = [
        _row(eps_t=300e-6),   # bit bottom 1
        _row(eps_t=400e-6),   # bit bottom 2 (max)
        _row(eps_z=500e-6),   # sub top 1
        _row(eps_z=350e-6),   # sub top 2
    ]
    eps_t, eps_v = extract_design_strains(results)
    assert eps_t == 400e-6
    assert eps_v == 500e-6


def test_uses_eps_r_when_larger_than_eps_t():
    """For dual-tire loading eps_r at r=155 can exceed eps_t — must be used."""
    results = [
        _row(eps_t=200e-6, eps_r=350e-6),
        _row(eps_t=180e-6, eps_r=100e-6),
        _row(eps_z=400e-6),
        _row(eps_z=350e-6),
    ]
    eps_t, _ = extract_design_strains(results)
    assert eps_t == 350e-6  # max of |eps_t| and |eps_r| across rows


def test_does_not_conflate_bit_and_sub_rows():
    """eps_t must NOT include subgrade rows even if their eps_t is huge."""
    results = [
        _row(eps_t=100e-6),                 # bit bottom (small)
        _row(eps_t=120e-6),                 # bit bottom (small)
        _row(eps_t=999e-6, eps_z=500e-6),   # sub top — eps_t here is irrelevant
        _row(eps_t=999e-6, eps_z=480e-6),   # sub top — eps_t here is irrelevant
    ]
    eps_t, eps_v = extract_design_strains(results)
    # If the helper had used max-over-all-rows it would return 999e-6 here.
    # With role-aware extraction it correctly returns the bit-bottom max.
    assert eps_t == 120e-6
    assert eps_v == 500e-6


# --- Explicit point_roles override ---

def test_explicit_roles_override_convention():
    """When point_roles is provided it wins over the default convention."""
    results = [
        _row(eps_t=100e-6, eps_z=999e-6),   # actually subgrade
        _row(eps_t=120e-6, eps_z=999e-6),   # actually subgrade
        _row(eps_t=200e-6),                 # actually bit
        _row(eps_t=250e-6),                 # actually bit
    ]
    eps_t, eps_v = extract_design_strains(
        results,
        point_roles={"bit_bottom": [2, 3], "sub_top": [0, 1]},
    )
    assert eps_t == 250e-6
    assert eps_v == 999e-6


# --- Edge cases: short / empty result lists ---

def test_empty_results_raises_clear_error():
    with pytest.raises(ValueError, match="empty"):
        extract_design_strains([])


def test_two_point_results_split_in_half():
    """For 2 results the helper splits 1/1 between bit and sub roles."""
    results = [
        _row(eps_t=200e-6),
        _row(eps_z=400e-6),
    ]
    eps_t, eps_v = extract_design_strains(results)
    assert eps_t == 200e-6
    assert eps_v == 400e-6


def test_single_point_degrades_to_rutting_only():
    """A single eval point cannot drive fatigue — eps_t collapses to 0."""
    eps_t, eps_v = extract_design_strains([_row(eps_z=400e-6)])
    assert eps_t == 0.0
    assert eps_v == 400e-6


def test_explicit_roles_missing_sub_top_raises():
    """Caller must provide sub_top indices — rutting strain is mandatory."""
    with pytest.raises(ValueError, match="sub_top"):
        extract_design_strains(
            [_row(eps_t=200e-6), _row(eps_t=200e-6)],
            point_roles={"bit_bottom": [0, 1]},
        )


def test_out_of_range_indices_in_roles_are_ignored():
    """Stray indices that exceed the result length must not crash."""
    results = [
        _row(eps_t=100e-6),
        _row(eps_z=400e-6),
    ]
    eps_t, eps_v = extract_design_strains(
        results,
        point_roles={"bit_bottom": [0, 99], "sub_top": [1, 200]},
    )
    assert eps_t == 100e-6
    assert eps_v == 400e-6


def test_granular_only_section_no_bituminous_indices():
    """No bit_bottom rows → eps_t = 0, eps_v from sub_top is correct."""
    results = [_row(eps_z=300e-6), _row(eps_z=450e-6)]
    eps_t, eps_v = extract_design_strains(
        results,
        point_roles={"bit_bottom": [], "sub_top": [0, 1]},
    )
    assert eps_t == 0.0
    assert eps_v == 450e-6
