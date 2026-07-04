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


# --- remap_eval_points_to_stack: interface probes must move with geometry ---

from mep_opt.advanced._strain_utils import remap_eval_points_to_stack


_BASE_STACK = [
    {"modulus": 3000, "poisson": 0.35, "thickness": 190},
    {"modulus": 200, "poisson": 0.35, "thickness": 480},
    {"modulus": 62, "poisson": 0.35, "thickness": 0},
]


def _perturb(layer_idx, delta):
    out = [dict(l) for l in _BASE_STACK]
    out[layer_idx]["thickness"] += delta
    return out


def test_remap_moves_subgrade_probe_with_thickened_granular():
    """+10 mm on the granular layer moves the 670.1 probe to 680.1."""
    pts = [{"z": 670.1, "r": 0}, {"z": 670.1, "r": 155}]
    remapped = remap_eval_points_to_stack(_BASE_STACK, _perturb(1, +10), pts)
    assert remapped[0]["z"] == pytest.approx(680.1)
    assert remapped[1]["z"] == pytest.approx(680.1)
    assert remapped[1]["r"] == 155  # r untouched


def test_remap_preserves_signed_offset_above_interface():
    """A probe just ABOVE the bituminous bottom (189.9) stays just above it."""
    pts = [{"z": 189.9, "r": 0}]
    remapped = remap_eval_points_to_stack(_BASE_STACK, _perturb(0, -5), pts)
    assert remapped[0]["z"] == pytest.approx(184.9)


def test_remap_moves_deep_probe_when_upper_layer_changes():
    """Thickening the TOP layer shifts every deeper interface too."""
    pts = [{"z": 670.1, "r": 0}]
    remapped = remap_eval_points_to_stack(_BASE_STACK, _perturb(0, +10), pts)
    assert remapped[0]["z"] == pytest.approx(680.1)


def test_remap_leaves_absolute_depth_probes_alone():
    """A mid-layer probe (not within tolerance of any interface) keeps its z."""
    pts = [{"z": 400.0, "r": 0}]
    remapped = remap_eval_points_to_stack(_BASE_STACK, _perturb(1, +10), pts)
    assert remapped[0]["z"] == pytest.approx(400.0)


def test_remap_is_identity_for_unchanged_geometry():
    pts = [{"z": 189.9, "r": 0}, {"z": 670.1, "r": 155}, {"z": 300.0, "r": 0}]
    remapped = remap_eval_points_to_stack(_BASE_STACK, _BASE_STACK, pts)
    assert [p["z"] for p in remapped] == [189.9, 670.1, 300.0]
