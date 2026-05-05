"""
Module D: 3D Strain Bulb Field
================================
Computes strain values on a 2D r-z grid for 3D visualization
of the strain bulb under wheel loading.
"""

import numpy as np
from mep_opt.solver.legacy_bridge import run_bridge_from_stack


def compute_strain_field(
    layers: list[dict],
    load_data: dict,
    r_steps: int = 12,
    z_steps: int = 25,
    r_max: float = 500.0,
) -> dict:
    """
    Compute a 2D strain field on an r-z grid.

    Args:
        layers: pavement stack (last entry is subgrade)
        load_data: must include ``load``, ``pressure``, ``is_dual``;
            ``spacing`` is required when ``is_dual`` is True (no silent
            fallback — a wrong dual-tire centre-to-centre distance produces
            a believable-looking bulb that's structurally wrong).

    Returns:
        {r_values, z_values, layer_interfaces, eps_z_grid, eps_t_grid, disp_z_grid}
        Grids are [z_index][r_index] arrays.
    """
    # Compute layer interfaces
    interfaces = []
    depth = 0.0
    for ld in layers[:-1]:  # exclude subgrade
        depth += ld["thickness"]
        interfaces.append(depth)

    total_depth = depth + 200.0  # extend 200mm into subgrade

    # Build grid
    r_values = np.linspace(0, r_max, r_steps).tolist()
    z_values = np.linspace(1.0, total_depth, z_steps).tolist()

    # Build load config dict for bridge — validate dual-tire geometry up
    # front so the visualization can never silently use a wrong spacing.
    is_dual = bool(load_data.get("is_dual", False))
    spacing_raw = load_data.get("spacing")
    if is_dual:
        if spacing_raw is None:
            raise ValueError(
                "Dual-tire load (is_dual=True) requires an explicit 'spacing' "
                "(centre-to-centre, mm). The strain field cannot guess at the "
                "wheel geometry."
            )
        try:
            spacing = float(spacing_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"spacing must be numeric, got {spacing_raw!r}") from exc
        if not (50.0 <= spacing <= 2000.0):
            raise ValueError(
                f"Dual-tire spacing {spacing} mm is outside the engineering "
                f"plausible 50–2000 mm range"
            )
    else:
        # Single-tire load: spacing has no physical meaning, but the bridge
        # interface still expects a number — supply 0 so we never propagate
        # a stale value from another configuration.
        spacing = 0.0

    load_cfg = {
        "load": load_data["load"],
        "pressure": load_data["pressure"],
        "is_dual": is_dual,
        "spacing": spacing,
    }

    # Compute strains at every grid point (one bridge call per z-row)
    eps_z_grid = []
    eps_t_grid = []
    disp_z_grid = []

    for z in z_values:
        eval_points = [{"z": z, "r": r} for r in r_values]
        results = run_bridge_from_stack(layers, load_cfg, eval_points)

        eps_z_row = [res["eps_z"] for res in results]
        eps_t_row = [res["eps_t"] for res in results]
        disp_z_row = [res.get("disp_z", 0.0) for res in results]

        eps_z_grid.append(eps_z_row)
        eps_t_grid.append(eps_t_row)
        disp_z_grid.append(disp_z_row)

    return {
        "r_values": r_values,
        "z_values": z_values,
        "layer_interfaces": interfaces,
        "layer_names": [ld.get("name", f"Layer {i+1}") for i, ld in enumerate(layers[:-1])],
        "eps_z_grid": eps_z_grid,
        "eps_t_grid": eps_t_grid,
        "disp_z_grid": disp_z_grid,
    }
