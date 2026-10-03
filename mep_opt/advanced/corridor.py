"""
Module E: Corridor Optimization (Batch CSV)
=============================================
Run the GA optimizer for multiple chainage sections from a CSV.
Returns per-section results and a unified corridor strategy.
"""

import csv
import io
import uuid
import asyncio
from typing import Optional, Union

from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel

# In-memory job store
_JOBS: dict[str, dict] = {}


def _to_reliability_level(value: Union[int, ReliabilityLevel]) -> ReliabilityLevel:
    """Normalize integer reliability input into the enum expected by IRC checks."""
    if isinstance(value, ReliabilityLevel):
        return value
    return {
        80: ReliabilityLevel.R80,
        90: ReliabilityLevel.R90,
        95: ReliabilityLevel.R95,
        98: ReliabilityLevel.R98,
        99: ReliabilityLevel.R99,
    }.get(int(value), ReliabilityLevel.R80)


# Required CSV columns mapped to acceptable header aliases (case-insensitive).
# Adding a new alias is the only safe way to accept a different header name —
# silent fallbacks like `row.get("CVPD", "800")` are intentionally avoided
# because they hide misspellings and missing data, both of which produce a
# corridor design quietly built on guessed numbers.
_CSV_COLUMN_ALIASES: dict[str, list[str]] = {
    "chainage": ["Chainage"],
    "cbr":      ["Subgrade_CBR", "CBR"],
    "cvpd":     ["CVPD"],
    "vdf":      ["VDF"],
    "ldf":      ["LDF"],
}


def parse_corridor_csv(csv_text: str) -> list[dict]:
    """
    Parse a corridor CSV with columns:
    Chainage, Subgrade_CBR (or CBR), CVPD, VDF, LDF.

    Every required column must be present in the header; otherwise a
    ``ValueError`` is raised with the missing column names listed. Empty
    or non-numeric cells inside a row also raise a ``ValueError`` that
    points back to the offending CSV row number.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or has no header row")

    # Case-insensitive alias resolution: build {canonical_field: actual_header}
    headers_by_lower = {(h or "").strip().lower(): h for h in reader.fieldnames}
    field_map: dict[str, str] = {}
    missing: list[str] = []
    for canonical, aliases in _CSV_COLUMN_ALIASES.items():
        match = next(
            (headers_by_lower[a.lower()] for a in aliases if a.lower() in headers_by_lower),
            None,
        )
        if match is None:
            missing.append(f"{canonical} (accepts: {', '.join(aliases)})")
        else:
            field_map[canonical] = match

    if missing:
        raise ValueError(
            f"Corridor CSV is missing required column(s): {missing}. "
            f"Found headers: {list(reader.fieldnames)}"
        )

    sections: list[dict] = []
    for line_no, row in enumerate(reader, start=2):  # +1 header, +1 1-index
        chainage_str = (row.get(field_map["chainage"]) or "").strip()
        if not chainage_str:
            raise ValueError(f"CSV row {line_no}: 'chainage' is empty")
        try:
            section = {
                "chainage": chainage_str,
                "cbr":  float(row[field_map["cbr"]]),
                "cvpd": float(row[field_map["cvpd"]]),
                "vdf":  float(row[field_map["vdf"]]),
                "ldf":  float(row[field_map["ldf"]]),
            }
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CSV row {line_no}: could not parse a numeric value "
                f"for chainage {chainage_str!r}: {exc}"
            ) from exc

        # Range sanity — the optimizer can't recover from these silently.
        if section["cbr"] <= 0:
            raise ValueError(f"CSV row {line_no}: cbr must be > 0 (got {section['cbr']})")
        if section["cvpd"] <= 0:
            raise ValueError(f"CSV row {line_no}: cvpd must be > 0 (got {section['cvpd']})")
        if section["vdf"] <= 0:
            raise ValueError(f"CSV row {line_no}: vdf must be > 0 (got {section['vdf']})")
        if not (0.0 < section["ldf"] <= 1.0):
            raise ValueError(
                f"CSV row {line_no}: ldf must be in (0, 1] (got {section['ldf']})"
            )
        sections.append(section)

    if not sections:
        raise ValueError("Corridor CSV has a header but no data rows")

    return sections


def _section_problem(section: dict, layer_constraints: list[dict],
                     growth_rate: float, design_life: int,
                     reliability: int, road_category: str = "other",
                     fixed_thicknesses: Optional[list] = None) -> OptimizationProblem:
    """Build the OptimizationProblem for one chainage section."""
    traffic = TrafficInput(
        initial_aadt=0,
        commercial_vehicles_per_day=section["cvpd"],
        traffic_growth_rate=growth_rate,
        design_life_years=design_life,
        lane_distribution_factor=section["ldf"],
        vehicle_damage_factor=section["vdf"],
    )
    subgrade = SubgradeInput(cbr=section["cbr"])

    layer_types: list[str] = []
    thickness_bounds: dict[str, tuple[float, float]] = {}
    layer_props: dict[str, dict] = {}
    for idx, c in enumerate(layer_constraints):
        l_type = c["layer_type"]
        layer_types.append(l_type)
        # Only pin a custom E when one is supplied. When E is None (e.g. for
        # unbound granular layers) it is omitted so build_layer_stack derives
        # the modulus from IRC:37-2018 Eq. 7.1 (thickness + support based)
        # rather than using a flat placeholder.
        layer_props[l_type] = {"nu": c["nu"]}
        if c.get("E") is not None:
            layer_props[l_type]["E"] = c["E"]

        if fixed_thicknesses is not None:
            t = float(fixed_thicknesses[idx])
            thickness_bounds[l_type] = (t, t)
        elif c.get("is_fixed"):
            fixed_t = float(
                c.get(
                    "fixed_thickness",
                    c.get("min_thickness", c.get("max_thickness", 0.0)),
                )
            )
            thickness_bounds[l_type] = (fixed_t, fixed_t)
        else:
            lo = float(c["min_thickness"])
            hi = float(c["max_thickness"])
            if lo > hi:
                raise ValueError(
                    f"layer_type {l_type!r}: min_thickness ({lo}) > "
                    f"max_thickness ({hi})"
                )
            thickness_bounds[l_type] = (lo, hi)

    return OptimizationProblem(
        traffic=traffic,
        subgrade=subgrade,
        reliability=_to_reliability_level(reliability),
        road_category=road_category,
        layer_types=layer_types,
        layer_props=layer_props,
        thickness_bounds=thickness_bounds,
    )


def verify_design_for_section(section: dict, layer_constraints: list[dict],
                              thicknesses: list, growth_rate: float,
                              design_life: int, reliability: int,
                              road_category: str = "other") -> dict:
    """Evaluate one fixed design against one section's traffic and subgrade."""
    problem = _section_problem(section, layer_constraints, growth_rate, design_life,
                               reliability, road_category, fixed_thicknesses=thicknesses)
    return SmartPavementSearch(problem)._evaluate([float(t) for t in thicknesses])


def _run_single_section(section: dict, layer_constraints: list[dict],
                        growth_rate: float, design_life: int,
                        reliability: int, road_category: str = "other") -> dict:
    """Run the optimizer for a single chainage section."""
    try:
        # Reject empty / malformed layer_constraints early so we surface a
        # clear corridor-section error instead of an opaque crash inside
        # the optimizer.
        if not layer_constraints:
            raise ValueError("layer_constraints must contain at least one layer")
        seen_types: set[str] = set()
        for c in layer_constraints:
            l_type = c.get("layer_type")
            if not l_type:
                raise ValueError("Every layer_constraint must specify layer_type")
            key = str(l_type).strip().upper()
            if key in seen_types:
                raise ValueError(f"Duplicate layer_type in constraints: {l_type}")
            seen_types.add(key)

        problem = _section_problem(section, layer_constraints, growth_rate,
                                   design_life, reliability, road_category)
        msa = problem.traffic.cumulative_msa()
        optimizer = SmartPavementSearch(problem)
        result = optimizer.run()

        # Extract the best design. An infeasible run still returns a
        # "Preliminary" placeholder in pareto_front, so feasibility must be
        # read from is_feasible — otherwise an inadequate section was
        # reported as "ok" with CDF 0 and folded into the corridor envelope.
        if result and getattr(result, "is_feasible", False) and result.pareto_front:
            best = result.pareto_front[0]
            return {
                "chainage": section["chainage"],
                "cbr": section["cbr"],
                "msa": round(msa, 2),
                "status": "ok",
                "thicknesses": [round(t, 1) for t in best.optimal_thicknesses],
                "total_thickness": round(sum(best.optimal_thicknesses), 1),
                "cost_per_km": best.cost,
                "co2_per_km": best.co2,
                "cdf_f": best.performance.get("CDF_fatigue", 0) if best.performance else 0,
                "cdf_r": best.performance.get("CDF_rutting", 0) if best.performance else 0,
                "cdf_ctb": best.performance.get("CDF_ctb") if best.performance else None,
            }
        else:
            return {
                "chainage": section["chainage"],
                "cbr": section["cbr"],
                "msa": round(msa, 2),
                "status": "no_adequate_design",
                "thicknesses": [],
                "total_thickness": 0,
                "cost_per_km": None,
                "co2_per_km": None,
                "cdf_f": None,
                "cdf_r": None,
                "cdf_ctb": None,
                "reason": (result.warnings or [None])[0] if result else None,
            }
    except Exception as e:
        return {
            "chainage": section["chainage"],
            "cbr": section["cbr"],
            "msa": 0,
            "status": f"error: {str(e)}",
            "thicknesses": [],
            "total_thickness": 0,
            "cost_per_km": None,
            "co2_per_km": None,
            "cdf_f": None,
            "cdf_r": None,
            "cdf_ctb": None,
        }


async def start_corridor_job(
    sections: list[dict],
    layer_constraints: list[dict],
    growth_rate: float = 0.05,
    design_life: int = 20,
    reliability: int = 80,
    road_category: str = "other",
) -> str:
    """Start an async corridor optimization job. Returns job_id."""
    job_id = str(uuid.uuid4())[:8]
    _JOBS[job_id] = {
        "status": "running",
        "total": len(sections),
        "completed": 0,
        "sections": [],
        "corridor_strategy": None,
    }

    async def _run():
        for i, section in enumerate(sections):
            result = await asyncio.to_thread(
                _run_single_section, section, layer_constraints,
                growth_rate, design_life, reliability, road_category,
            )
            _JOBS[job_id]["sections"].append(result)
            _JOBS[job_id]["completed"] = i + 1

        # Compute unified corridor strategy (max thickness per layer position)
        ok_sections = [s for s in _JOBS[job_id]["sections"] if s["status"] == "ok"]
        if ok_sections:
            n_layers = max(len(s["thicknesses"]) for s in ok_sections)
            unified = []
            for li in range(n_layers):
                layer_vals = [s["thicknesses"][li] for s in ok_sections if li < len(s["thicknesses"])]
                unified.append(round(max(layer_vals), 1) if layer_vals else 0)

            # The envelope (max per layer) is not guaranteed adequate (e.g.
            # eps_t is non-monotone in thin bituminous layers), so verify it
            # against EVERY section's traffic and subgrade.
            failing = []
            for sec in sections:
                try:
                    chk = await asyncio.to_thread(
                        verify_design_for_section, sec, layer_constraints, unified,
                        growth_rate, design_life, reliability, road_category,
                    )
                    if not chk.get("overall_adequate"):
                        failing.append(sec["chainage"])
                except Exception as exc:  # pragma: no cover - defensive
                    failing.append(f"{sec['chainage']} (error: {exc})")
            _JOBS[job_id]["corridor_strategy"] = {
                "unified_thicknesses": unified,
                "total_thickness": round(sum(unified), 1),
                "sections_optimized": len(ok_sections),
                "sections_total": len(sections),
                "unified_adequate_all_sections": not failing,
                "unified_failing_sections": failing,
            }

        _JOBS[job_id]["status"] = "complete"

    asyncio.create_task(_run())
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    """Get the current status of a corridor job."""
    return _JOBS.get(job_id)
