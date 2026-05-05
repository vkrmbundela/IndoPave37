"""
Shared strain extraction utilities for the advanced analysis modules.

Both the sensitivity heatmap and the Monte Carlo modules need to pull
two specific strain quantities out of an IIT Pave bridge result list:

  * eps_t : max horizontal tensile strain at the **bottom of bituminous**
            (drives the IRC fatigue criterion)
  * eps_v : max vertical compressive strain at the **top of subgrade**
            (drives the IRC rutting criterion)

Earlier versions of those modules collapsed the result list with
``max(... for r in res)`` for both quantities. That is "safer" than the
positional slicing the optimizer originally used (it does not crash when
``len(res) < 2``) but it is still wrong: it conflates eps_t at the
bottom of bituminous with eps_t at the top of subgrade. If the caller
supplies extra eval points or a different point order, the wrong row
quietly becomes the answer.

This helper centralises the role-aware extraction so the same correct
behaviour applies everywhere the advanced modules read bridge output.
"""

from typing import Dict, List, Optional, Tuple


def extract_design_strains(
    results: List[dict],
    point_roles: Optional[Dict[str, List[int]]] = None,
) -> Tuple[float, float]:
    """
    Extract (eps_t, eps_v) from a bridge result list using role-aware indices.

    Args:
        results: list of dicts returned by ``run_bridge_from_stack``
        point_roles: optional explicit mapping, e.g.
            ``{"bit_bottom": [0, 1], "sub_top": [2, 3]}``.
            When omitted, the function falls back to the convention used
            by the optimizer and the dashboard: the first two eval points
            are at the bottom of bituminous and the next two are at the
            top of subgrade.

    Returns:
        ``(eps_t, eps_v)`` in absolute-magnitude form.

    Raises:
        ValueError: if ``results`` is empty or contains no usable
            subgrade row to derive eps_v from. In that case the caller
            should treat the design as un-evaluable rather than guess.
    """
    if not results:
        raise ValueError("Cannot extract strains: bridge returned empty results")

    n = len(results)

    if point_roles is None:
        # Default convention: first 2 points are bituminous bottom,
        # next 2 are subgrade top. Matches the optimizer's internal
        # eval_points layout in SmartPavementSearch._evaluate.
        if n >= 4:
            bit_idx = [0, 1]
            sub_idx = [2, 3]
        elif n >= 2:
            # Granular-only or compact stack: split in half.
            mid = max(1, n // 2)
            bit_idx = list(range(mid))
            sub_idx = list(range(mid, n))
        else:
            # Single point — degrade gracefully: use it for rutting only,
            # and report no fatigue strain (no bituminous interface point).
            bit_idx = []
            sub_idx = [0]
    else:
        bit_idx = list(point_roles.get("bit_bottom") or [])
        sub_idx = list(point_roles.get("sub_top") or [])
        if not sub_idx:
            raise ValueError(
                "point_roles must include a non-empty 'sub_top' index list "
                "to derive the rutting strain"
            )

    # Clip to in-range indices so a partial bridge response never crashes.
    bit_rows = [results[i] for i in bit_idx if 0 <= i < n]
    sub_rows = [results[i] for i in sub_idx if 0 <= i < n]

    if not sub_rows:
        raise ValueError(
            f"No valid subgrade rows in results (had {n} rows, sub_idx={sub_idx})"
        )

    if bit_rows:
        # Use max of tangential AND radial — see SmartPavementSearch._evaluate
        # for the full rationale. eps_r can dominate at r=155 under dual tires.
        eps_t = max(
            max(abs(r["eps_t"]), abs(r.get("eps_r", 0.0)))
            for r in bit_rows
        )
    else:
        # No bituminous bottom point provided — granular-only section.
        # Fatigue is not the governing criterion; report 0 so CDF_fatigue
        # collapses to 0 inside check_design_adequacy().
        eps_t = 0.0

    eps_v = max(abs(r["eps_z"]) for r in sub_rows)
    return eps_t, eps_v
