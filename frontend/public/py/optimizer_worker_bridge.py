"""
Optimizer Web Worker Bridge
===========================
Bridges JSON requests from the Web Worker JS thread to the mep_opt python package.
Allows client-side optimization via Pyodide.
"""

import json
import time
import math
from typing import Any, Dict, List, Optional, Union
import numpy as np

from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel, AxleLoadGroup
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.solver.geosynthetic import get_mif
from mep_opt.solver import sp72 as _sp72


def _to_native(value: Any) -> Any:
    """Convert NumPy types to Python native types for JSON serialization.
    Replaces NaN/Inf with None to ensure valid JSON output."""
    if isinstance(value, dict):
        return {k: _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_to_native(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        v = value.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def run_optimize(request_json_str: str) -> str:
    try:
        data = json.loads(request_json_str)
        
        cvpd = float(data.get("cvpd"))
        growth_rate = float(data.get("growth_rate"))
        design_life = int(data.get("design_life"))
        vdf = float(data.get("vdf", 2.5))
        lane_factor = float(data.get("lane_factor", 0.75))
        subgrade_cbr = float(data.get("subgrade_cbr"))
        reliability_str = data.get("reliability", "90%")
        temperature = float(data.get("temperature", 35.0))
        wheel_load = float(data.get("wheel_load", 20000.0))
        tire_pressure = float(data.get("tire_pressure", 0.56))
        # IRC:37-2018 §3.6.1 standard axle is a DUAL wheel set — Dual default.
        wheel_type = data.get("wheel_type", "Dual")
        wheel_spacing = float(data.get("wheel_spacing", 310.0))
        # IRC:37-2018 §3.6.2 fatigue mix volumetrics (bottom bituminous layer).
        air_voids = float(data.get("air_voids", 3.0))
        bitumen_volume = float(data.get("bitumen_volume", 11.5))
        debug = bool(data.get("debug", False))
        optimize_by_cost = bool(data.get("optimize_by_cost", False))
        optimize_by_co2 = bool(data.get("optimize_by_co2", False))
        ctb_per_class_bridge_recompute = bool(data.get("ctb_per_class_bridge_recompute", False))
        
        # Parse axle spectrum
        raw_spectrum = data.get("ctb_axle_spectrum")
        ctb_axle_spectrum = None
        if raw_spectrum:
            ctb_axle_spectrum = [
                AxleLoadGroup(
                    axle_type=item.get("axle_type"),
                    load_kn=float(item.get("load_kn")),
                    expected_repetitions=float(item.get("expected_repetitions"))
                ) for item in raw_spectrum
            ]
            
        # Parse layers
        raw_layers = data.get("layers", [])
        l_types = []
        bounds = {}
        layer_props = {}
        
        for l in raw_layers:
            layer_type = l.get("layer_type")
            # E null/omitted = "auto": granular moduli derive from IRC:37-2018
            # Eq. 7.1 per candidate thickness (mirrors mep_opt.web.main).
            raw_E = l.get("E")
            E = float(raw_E) if raw_E is not None else None
            nu = float(l.get("nu"))
            geogrid = l.get("geogrid")
            is_fixed = bool(l.get("is_fixed", False))
            fixed_thickness = float(l.get("fixed_thickness", 0.0))
            min_thickness = float(l.get("min_thickness", 0.0))
            max_thickness = float(l.get("max_thickness", 0.0))

            if layer_type.lower() != "subgrade":
                l_types.append(layer_type)

            layer_props[layer_type] = {'nu': nu}
            if E is not None:
                layer_props[layer_type]['E'] = E
            if geogrid:
                layer_props[layer_type]['geogrid'] = geogrid
                
            if is_fixed:
                bounds[layer_type] = (fixed_thickness, fixed_thickness)
            else:
                bounds[layer_type] = (min_thickness, max_thickness)
                
        sub_custom = layer_props.get('Subgrade')
        if sub_custom and sub_custom.get('E') is not None:
            layer_props['Subgrade'] = {k: v for k, v in sub_custom.items() if k != 'E'}
            
        # Parse material rates
        raw_rates = data.get("material_rates")
        material_rates = None
        if raw_rates:
            material_rates = {}
            for k, val in raw_rates.items():
                if isinstance(val, dict):
                    # MaterialRateOverride
                    material_rates[k] = {
                        "cost_per_cum": val.get("cost_per_cum"),
                        "co2_per_cum": val.get("co2_per_cum"),
                        "density": val.get("density"),
                        "transport_co2_factor": val.get("transport_co2_factor")
                    }
                    # Filter out None values
                    material_rates[k] = {mk: mv for mk, mv in material_rates[k].items() if mv is not None}
                else:
                    material_rates[k] = val
                    
        # Parse points
        raw_points = data.get("points")
        points = None
        if raw_points:
            points = [{"z": float(p.get("z")), "r": float(p.get("r"))} for p in raw_points]
            
        # Setup inputs
        traffic = TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=cvpd,
            traffic_growth_rate=growth_rate,
            design_life_years=design_life,
            lane_distribution_factor=lane_factor,
            vehicle_damage_factor=vdf,
        )

        subgrade = SubgradeInput(cbr=subgrade_cbr)

        # IRC:37-2018 §3.7 defines only R80 and R90; the optimizer
        # auto-escalates R80->R90 for design traffic >= 20 msa.
        rel_map = {
            "80%": ReliabilityLevel.R80,
            "90%": ReliabilityLevel.R90,
        }
        reliability = rel_map.get(reliability_str, ReliabilityLevel.R90)
        
        # Build Problem
        problem = OptimizationProblem(
            traffic=traffic,
            subgrade=subgrade,
            reliability=reliability,
            temperature=temperature,
            air_voids=air_voids,
            bitumen_volume=bitumen_volume,
            layer_types=l_types,
            layer_props=layer_props,
            thickness_bounds=bounds,
            material_rates=material_rates,
            wheel_load=wheel_load,
            tire_pressure=tire_pressure,
            wheel_type=wheel_type,
            wheel_spacing=wheel_spacing,
            ctb_axle_spectrum=ctb_axle_spectrum,
            ctb_per_class_bridge_recompute=ctb_per_class_bridge_recompute,
            eval_points=points,
            optimize_by_cost=optimize_by_cost,
            optimize_by_co2=optimize_by_co2,
        )
        
        optimizer = SmartPavementSearch(problem)
        # Cooperatively stop after 300 seconds if needed, but in browser we don't have asyncio.wait_for hard ceiling easily,
        # so we rely on the Cooperative deadline.
        deadline = time.monotonic() + 300.0
        
        result = optimizer.run(deadline=deadline)
        
        # Format output
        adequate_designs_response = []
        if result.pareto_front:
            for sol in result.pareto_front:
                perf = sol.performance or {}
                if not perf.get("overall_adequate", False):
                    continue

                optimal_layers = []
                for i, t in enumerate(sol.optimal_thicknesses):
                    optimal_layers.append({
                        "type": result.layer_types[i],
                        "thickness": round(t, 1),
                    })
                adequate_designs_response.append({
                    "optimal_layers": optimal_layers,
                    "total_thickness": round(sum(sol.optimal_thicknesses), 1),
                    # Cost & CO2 returned only when their objective is enabled
                    # (the Economy / Sustainable archetypes only appear then).
                    "cost": round(sol.cost, 0) if (optimize_by_cost and sol.cost is not None) else None,
                    "co2": round(sol.co2, 1) if (optimize_by_co2 and sol.co2 is not None) else None,
                    "details": _to_native(perf)
                })

        errors_out = None
        if debug:
            raw_errors = getattr(result, 'errors', None) or []
            errors_out = [str(e) for e in raw_errors]

        reinforcement_out = []
        for l in raw_layers:
            g = l.get("geogrid")
            if g:
                reinforcement_out.append({
                    "layer": l.get("layer_type"),
                    "geogrid": g,
                    "mif": round(get_mif(subgrade.modulus, g), 3),
                })

        sp72_cls = _sp72.classify(
            cvpd=cvpd, vdf=vdf, growth_rate=growth_rate,
            design_life_years=design_life, lane_factor=lane_factor,
            cbr=subgrade_cbr,
        )
        sp72_out = {
            "is_low_volume": sp72_cls.is_low_volume,
            "esal": round(sp72_cls.esal, 0),
            "msa": round(sp72_cls.msa, 3),
            "traffic_category": sp72_cls.traffic_category,
            "surfacing_hint": sp72_cls.surfacing_hint,
            "subgrade_class": sp72_cls.subgrade_class,
            "subgrade_class_name": sp72_cls.subgrade_class_name,
            "blacktop_required": sp72_cls.blacktop_required,
            "min_base_thickness_mm": sp72_cls.min_base_thickness_mm,
            "advisory": sp72_cls.advisory,
        }
        
        return json.dumps({
            "status": "success",
            "adequate_designs": adequate_designs_response,
            "is_adequate": bool(result.is_feasible),
            "errors": errors_out,
            "warnings": list(getattr(result, 'warnings', None) or []),
            "reinforcement": reinforcement_out,
            "sp72": sp72_out,
        })
        
    except Exception as e:
        import traceback
        return json.dumps({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        })
