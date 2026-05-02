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
from typing import Optional

from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel

# In-memory job store
_JOBS: dict[str, dict] = {}


def _to_reliability_level(value: int | ReliabilityLevel) -> ReliabilityLevel:
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


def parse_corridor_csv(csv_text: str) -> list[dict]:
    """
    Parse a corridor CSV with columns:
    Chainage, Subgrade_CBR, CVPD, VDF, LDF
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    sections = []
    for row in reader:
        sections.append({
            "chainage": row.get("Chainage", "").strip(),
            "cbr": float(row.get("Subgrade_CBR", row.get("CBR", "8"))),
            "cvpd": float(row.get("CVPD", row.get("cvpd", "800"))),
            "vdf": float(row.get("VDF", row.get("vdf", "2.5"))),
            "ldf": float(row.get("LDF", row.get("ldf", "0.75"))),
        })
    return sections


def _run_single_section(section: dict, layer_constraints: list[dict],
                        growth_rate: float, design_life: int,
                        reliability: int) -> dict:
    """Run GA optimization for a single chainage section."""
    try:
        traffic = TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=section["cvpd"],
            traffic_growth_rate=growth_rate,
            design_life_years=design_life,
            lane_distribution_factor=section["ldf"],
            vehicle_damage_factor=section["vdf"],
        )
        msa = traffic.cumulative_msa()
        subgrade = SubgradeInput(cbr=section["cbr"])

        layer_types: list[str] = []
        thickness_bounds: dict[str, tuple[float, float]] = {}
        layer_props: dict[str, dict] = {}
        for c in layer_constraints:
            l_type = c["layer_type"]
            layer_types.append(l_type)
            layer_props[l_type] = {"E": c["E"], "nu": c["nu"]}

            if c.get("is_fixed"):
                fixed_t = float(
                    c.get(
                        "fixed_thickness",
                        c.get("min_thickness", c.get("max_thickness", 0.0)),
                    )
                )
                thickness_bounds[l_type] = (fixed_t, fixed_t)
            else:
                thickness_bounds[l_type] = (
                    float(c["min_thickness"]),
                    float(c["max_thickness"]),
                )

        # Build optimization problem
        problem = OptimizationProblem(
            traffic=traffic,
            subgrade=subgrade,
            reliability=_to_reliability_level(reliability),
            layer_types=layer_types,
            layer_props=layer_props,
            thickness_bounds=thickness_bounds,
        )
        optimizer = SmartPavementSearch(problem)
        result = optimizer.run()

        # Extract best (economy) design
        if result and hasattr(result, "pareto_front") and result.pareto_front:
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
            }
        else:
            return {
                "chainage": section["chainage"],
                "cbr": section["cbr"],
                "msa": round(msa, 2),
                "status": "no_adequate_design",
                "thicknesses": [],
                "total_thickness": 0,
                "cost_per_km": 0,
                "co2_per_km": 0,
                "cdf_f": 0,
                "cdf_r": 0,
            }
    except Exception as e:
        return {
            "chainage": section["chainage"],
            "cbr": section["cbr"],
            "msa": 0,
            "status": f"error: {str(e)}",
            "thicknesses": [],
            "total_thickness": 0,
            "cost_per_km": 0,
            "co2_per_km": 0,
            "cdf_f": 0,
            "cdf_r": 0,
        }


async def start_corridor_job(
    sections: list[dict],
    layer_constraints: list[dict],
    growth_rate: float = 0.05,
    design_life: int = 20,
    reliability: int = 80,
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
                growth_rate, design_life, reliability,
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

            _JOBS[job_id]["corridor_strategy"] = {
                "unified_thicknesses": unified,
                "total_thickness": round(sum(unified), 1),
                "sections_optimized": len(ok_sections),
                "sections_total": len(sections),
            }

        _JOBS[job_id]["status"] = "complete"

    asyncio.create_task(_run())
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    """Get the current status of a corridor job."""
    return _JOBS.get(job_id)
