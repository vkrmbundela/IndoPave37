"""
IndoPave-37 FastAPI Backend
=========================
Serves the web UI and provides analysis/optimization API endpoints.
"""

import asyncio
import logging
import os
import math
import time
from typing import List, Dict, Any, Optional, Union

import numpy as np
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

# Project Imports
from mep_opt.solver.legacy_bridge import is_bridge_available, run_bridge_from_stack
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.solver.irc37 import AxleLoadGroup

# Initialize Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(title="IndoPave-37 API", version="3.4.2")

# Configure CORS. This is a stateless public API (no cookies/sessions/auth),
# so credentials are not used. A wildcard origin combined with
# allow_credentials=True is invalid per the CORS spec (browsers refuse the
# `Access-Control-Allow-Origin: *` + credentials combination), so credentials
# are explicitly disabled to keep the wildcard valid.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Advanced Engineering Modules (v2) — all routes under /api/v2/
try:
    from mep_opt.advanced.router import advanced_router
    app.include_router(advanced_router)
except ImportError:
    logger.warning("Advanced router could not be imported. Some V2 endpoints will be missing.")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Welcome page with redirection to the official GitHub Pages frontend."""
    return """
    <html>
        <head>
            <title>IndoPave-37 API</title>
            <style>
                body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #0f172a; color: white; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .card { background: #1e293b; padding: 2.5rem; border-radius: 1.5rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); text-align: center; max-width: 450px; border: 1px solid #334155; }
                h1 { color: #38bdf8; margin-bottom: 1rem; font-size: 2rem; }
                p { color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }
                .btn { background: #0284c7; color: white; text-decoration: none; padding: 0.75rem 1.5rem; border-radius: 0.5rem; font-weight: 600; transition: all 0.2s; display: inline-block; }
                .btn:hover { background: #0ea5e9; transform: translateY(-2px); }
                .status { margin-top: 1.5rem; font-size: 0.8rem; color: #475569; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>IndoPave-37 Backend</h1>
                <p>The API server is <strong>Online</strong>. To access the interactive engineering dashboard, please visit the official deployment on GitHub Pages.</p>
                <a href="https://vkrmbundela.github.io/IndoPave37/" class="btn">Go to Dashboard</a>
                <div class="status">v3.4.2 Production API</div>
            </div>
        </body>
    </html>
    """
@app.get("/health")
async def health_check():
    # Native solver is pure Python and always available; bridge is optional.
    return {
        "status": "healthy",
        "solver_native": True,
        "solver_bridge": is_bridge_available(),
    }


# Mount frontend assets after API routes to avoid conflicts
# Static files for the frontend (images, scripts, etc.)
if os.path.exists("frontend/dist"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Serve index.html for all non-API paths (SPA routing)
        if full_path.startswith("api/") or full_path.startswith("health"):
             raise HTTPException(status_code=404)
        
        file_path = os.path.join("frontend/dist", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse("frontend/dist/index.html")


# ---------------------------------------------------------------------------
# Pydantic Models — Analysis API
# ---------------------------------------------------------------------------

class LayerInput(BaseModel):
    E: float
    nu: float
    h: float  # 0 for infinite (half-space)

    @field_validator("E")
    @classmethod
    def e_positive(cls, v):
        if v <= 0:
            raise ValueError("Elastic modulus E must be positive")
        return v

    @field_validator("nu")
    @classmethod
    def nu_in_range(cls, v):
        if not (0.0 <= v < 0.5):
            raise ValueError("Poisson ratio nu must be in [0, 0.5)")
        return v

    @field_validator("h")
    @classmethod
    def h_non_negative(cls, v):
        if v < 0:
            raise ValueError("Layer thickness h must be >= 0")
        return v


class AnalysisPointInput(BaseModel):
    z: float
    r: float


class SolveRequest(BaseModel):
    layers: List[LayerInput]
    wheel_load: float = 20000.0     # Load per wheel (N)
    tire_pressure: float = 0.56     # Contact pressure (MPa)
    points: List[AnalysisPointInput]
    # IRC:37-2018 §3.6.1 standard axle = dual wheel (two 20 kN wheels at
    # 310 mm c/c). Dual is therefore the IRC-correct default.
    wheel_type: str = "Dual"        # "Single" or "Dual"
    wheel_spacing: float = 310.0    # Center-to-center spacing (mm) for dual

    @field_validator("wheel_load")
    @classmethod
    def load_positive(cls, v):
        if v <= 0:
            raise ValueError("wheel_load must be positive")
        return v

    @field_validator("tire_pressure")
    @classmethod
    def pressure_positive(cls, v):
        if v <= 0:
            raise ValueError("tire_pressure must be positive")
        return v

    @field_validator("wheel_type")
    @classmethod
    def valid_wheel_type(cls, v):
        if v.lower() not in ("single", "dual"):
            raise ValueError("wheel_type must be 'Single' or 'Dual'")
        return v

    @field_validator("wheel_spacing")
    @classmethod
    def spacing_positive(cls, v):
        if v <= 0:
            raise ValueError("wheel_spacing must be positive")
        return v


class SolveResponse(BaseModel):
    status: str
    results: List[dict]
    max_disp: float
    max_strain_t: float
    max_strain_c: float


# ---------------------------------------------------------------------------
# Pydantic Models — Optimization API
# ---------------------------------------------------------------------------

class LayerConstraint(BaseModel):
    layer_type: str  # BC, DBM, WMM, GSB, etc.
    min_thickness: float
    max_thickness: float
    is_fixed: bool = False
    fixed_thickness: float = 0.0
    E: float
    nu: float
    geogrid: Optional[str] = None  # geosynthetic reinforcement: PP30/PET30/PET60/none

    @field_validator("E")
    @classmethod
    def e_positive(cls, v):
        if v <= 0:
            raise ValueError("Elastic modulus E must be positive")
        return v

    @field_validator("geogrid")
    @classmethod
    def geogrid_valid(cls, v):
        if v in (None, "", "none"):
            return None
        from mep_opt.solver.geosynthetic import MIF_TABLE
        if v not in MIF_TABLE:
            raise ValueError(
                f"geogrid must be one of {sorted(MIF_TABLE)} or null (got {v!r})"
            )
        return v

    @field_validator("nu")
    @classmethod
    def nu_in_range(cls, v):
        if not (0.0 <= v < 0.5):
            raise ValueError("Poisson ratio nu must be in [0, 0.5)")
        return v

    @field_validator("min_thickness", "max_thickness")
    @classmethod
    def thickness_non_negative(cls, v):
        if v < 0:
            raise ValueError("Thickness must be non-negative (>= 0)")
        return v

    @field_validator("fixed_thickness")
    @classmethod
    def fixed_thickness_non_negative(cls, v):
        if v < 0:
            raise ValueError("fixed_thickness must be non-negative (>= 0)")
        return v

    @model_validator(mode='after')
    def check_thickness_bounds(self) -> 'LayerConstraint':
        if not self.is_fixed:
            if self.min_thickness > self.max_thickness:
                raise ValueError(
                    f"min_thickness ({self.min_thickness}) cannot be greater than "
                    f"max_thickness ({self.max_thickness})"
                )
        return self


class MaterialRateOverride(BaseModel):
    """Optional per-field override of a single material's unit rate."""
    cost_per_cum: Optional[float] = None       # ₹/m³
    co2_per_cum: Optional[float] = None        # kg CO₂/m³
    density: Optional[float] = None            # kg/m³
    transport_co2_factor: Optional[float] = None  # kg CO₂ / (tonne · km)

    @field_validator("cost_per_cum")
    @classmethod
    def cost_positive(cls, v):
        if v is not None and v < 0:
            raise ValueError("cost_per_cum must be non-negative")
        return v

    @field_validator("co2_per_cum")
    @classmethod
    def co2_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("co2_per_cum must be non-negative")
        return v

    @field_validator("density")
    @classmethod
    def density_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("density must be positive")
        return v


class AxleLoadGroupInput(BaseModel):
    axle_type: str
    load_kn: float
    expected_repetitions: float

    @field_validator("load_kn")
    @classmethod
    def load_kn_positive(cls, v):
        if v <= 0:
            raise ValueError("load_kn must be positive")
        return v

    @field_validator("expected_repetitions")
    @classmethod
    def repetitions_non_negative(cls, v):
        if v < 0:
            raise ValueError("expected_repetitions must be non-negative")
        return v


class OptimizeRequest(BaseModel):
    cvpd: float
    growth_rate: float
    design_life: int
    vdf: float = 2.5
    lane_factor: float = 0.75
    ctb_axle_spectrum: Optional[List[AxleLoadGroupInput]] = None
    ctb_per_class_bridge_recompute: bool = False
    subgrade_cbr: float
    reliability: str = "90%"
    temperature: float = 35.0       # Pavement temperature (deg C)
    # IRC:37-2018 §3.6.2 fatigue mix volumetrics for the bottom bituminous
    # layer. Defaults match the IRC Annex-II worked example.
    air_voids: float = 3.0          # Va (%)
    bitumen_volume: float = 11.5    # Vbe (%)
    layers: List[LayerConstraint]

    # Optional per-layer-type unit-rate override for cost-aware optimization.
    # Each entry may be a number (₹/m³ cost-only override) or an object with
    # any subset of {cost_per_cum, co2_per_cum, density, transport_co2_factor}.
    # Layer types not specified use the IRC/MORTH SoR defaults.
    material_rates: Optional[Dict[str, Union[float, MaterialRateOverride]]] = None
    # Optional load & wheel config to ensure Optimize matches Evaluate
    wheel_load: float = 20000.0
    tire_pressure: float = 0.56
    # IRC:37-2018 §3.6.1 mandates a dual-wheel standard axle — Dual default.
    wheel_type: str = "Dual"
    wheel_spacing: float = 310.0
    # Optional analysis points for the optimizer (list of {z, r})
    points: Optional[List[AnalysisPointInput]] = None
    # Debug toggle: when true, return evaluation errors in the response (if any)
    debug: bool = False

    # Cost and CO₂ optimization toggles — when False (default), the
    # optimizer ranks by total_thickness and returns null for the
    # respective metric. Enable only when the user supplies material_rates.
    optimize_by_cost: bool = False
    optimize_by_co2: bool = False

    @field_validator("material_rates")
    @classmethod
    def normalize_material_rates(cls, v):
        if v is None:
            return v
        # Convert MaterialRateOverride models to plain dicts so the optimizer's
        # resolver can merge them with defaults uniformly.
        normalized: Dict[str, Any] = {}
        for k, val in v.items():
            if isinstance(val, MaterialRateOverride):
                normalized[k] = val.model_dump(exclude_none=True)
            else:
                normalized[k] = val
        return normalized

    @field_validator("cvpd")
    @classmethod
    def cvpd_positive(cls, v):
        if v <= 0:
            raise ValueError("cvpd (commercial vehicles per day) must be positive")
        return v

    @field_validator("growth_rate")
    @classmethod
    def growth_rate_range(cls, v):
        if not (-0.05 <= v <= 0.20):
            raise ValueError("growth_rate must be between -0.05 and 0.20")
        return v

    @field_validator("design_life")
    @classmethod
    def design_life_positive(cls, v):
        if v <= 0:
            raise ValueError("design_life must be positive")
        return v

    @field_validator("subgrade_cbr")
    @classmethod
    def cbr_positive(cls, v):
        if v <= 0:
            raise ValueError("subgrade_cbr must be positive")
        return v

    @field_validator("air_voids")
    @classmethod
    def air_voids_range(cls, v):
        # Design air-void content of bituminous mixes is typically 3–7%.
        if not (1.0 <= v <= 12.0):
            raise ValueError("air_voids (Va, %) must be between 1 and 12")
        return v

    @field_validator("bitumen_volume")
    @classmethod
    def bitumen_volume_range(cls, v):
        # Effective bitumen volume Vbe is typically ~9–13% by volume.
        if not (5.0 <= v <= 20.0):
            raise ValueError("bitumen_volume (Vbe, %) must be between 5 and 20")
        return v

    @field_validator("reliability")
    @classmethod
    def valid_reliability(cls, v):
        # IRC:37-2018 §3.7 defines performance models for ONLY two reliability
        # levels: 80% and 90%. Earlier the API also accepted 95/98/99% which
        # were then silently collapsed to R90 — misleading the user into
        # thinking they had a more conservative design. Only the two
        # IRC-defined levels are accepted now.
        valid = {"80%", "90%"}
        if v not in valid:
            raise ValueError(
                "reliability must be '80%' or '90%' — IRC:37-2018 defines "
                "performance models for these two levels only."
            )
        return v

    @field_validator("wheel_load")
    @classmethod
    def wheel_load_range(cls, v):
        # Indian highway wheel loads typically span ~5–80 kN per wheel for
        # 8–18 t commercial axles. Allow a generous 1–200 kN window so the
        # validator catches pathological values (e.g., 1e9 N) without
        # second-guessing legitimate research scenarios.
        if not (1_000.0 <= v <= 200_000.0):
            raise ValueError(
                "wheel_load (N per wheel) must be between 1,000 and 200,000"
            )
        return v

    @field_validator("tire_pressure")
    @classmethod
    def tire_pressure_range(cls, v):
        # Realistic tire contact pressures: 0.4–1.2 MPa. Accept 0.1–2.0
        # to remain permissive for non-standard cases.
        if not (0.1 <= v <= 2.0):
            raise ValueError(
                "tire_pressure (MPa) must be between 0.1 and 2.0"
            )
        return v

    @field_validator("wheel_type")
    @classmethod
    def optimize_wheel_type(cls, v):
        if v is None or v.lower() not in ("single", "dual"):
            raise ValueError("wheel_type must be 'Single' or 'Dual'")
        return v

    @field_validator("wheel_spacing")
    @classmethod
    def wheel_spacing_range(cls, v):
        if not (50.0 <= v <= 2_000.0):
            raise ValueError(
                "wheel_spacing (mm) must be between 50 and 2000"
            )
        return v

    @field_validator("layers")
    @classmethod
    def validate_layer_stack(cls, v):
        if not v:
            raise ValueError("At least one layer is required")
        if len(v) > 20:
            raise ValueError("Maximum 20 layers supported (got %d)" % len(v))
        types = [str(l.layer_type).strip() for l in v]
        # Duplicates make layer_props / thickness_bounds dicts ambiguous.
        seen = set()
        dups = []
        for t in types:
            key = t.upper()
            if key in seen:
                dups.append(t)
            else:
                seen.add(key)
        if dups:
            raise ValueError(
                f"Duplicate layer_type entries are not allowed: {sorted(set(dups))}"
            )
        return v


class AdequateDesignSchema(BaseModel):
    optimal_layers: List[dict]
    total_thickness: float
    cost: Optional[float] = None           # Only populated when optimize_by_cost=True
    co2: Optional[float] = None            # Only populated when optimize_by_co2=True
    details: Optional[dict] = None

class OptimizeResponse(BaseModel):
    status: str
    adequate_designs: List[AdequateDesignSchema]
    is_adequate: bool
    errors: Optional[List[str]] = None
    warnings: List[str] = Field(default_factory=list)
    reinforcement: List[dict] = Field(default_factory=list)  # [{layer, geogrid, mif}]
    sp72: Optional[dict] = None  # IRC:SP:72 low-volume classification (when <= 2 MSA)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/solve", response_model=SolveResponse)
async def solve_pavement(data: SolveRequest):
    try:
        logger.info("Received solve request")

        # 1. Build layer stack
        solver_stack = [{"modulus": l.E, "poisson": l.nu, "thickness": l.h} for l in data.layers]
        
        # 2. Build load config
        load_cfg = {
            "load": data.wheel_load,
            "pressure": data.tire_pressure,
            "is_dual": data.wheel_type.lower() == "dual",
            "spacing": data.wheel_spacing
        }
        
        eval_points = [{"z": p.z, "r": p.r} for p in data.points]

        # 3. Solve via the unified facade: native Python Burmister solver
        #    first, legacy .EXE bridge as automatic fallback. The native
        #    solver needs no executable, so no bridge-availability gate here.
        raw_results = run_bridge_from_stack(solver_stack, load_cfg, eval_points)

        # 6. Format Output
        output_results = []
        max_disp = 0.0
        max_eps_t = 0.0
        max_eps_c = 0.0

        for i, r in enumerate(raw_results):
            res_dict = {
                "id": i,
                "z": data.points[i].z,
                "r": data.points[i].r,
                "sigma_z": r.get("sigma_z", 0.0),
                "sigma_r": r.get("sigma_r", 0.0),
                "sigma_t": r.get("sigma_t", 0.0),
                "tau_rz": r.get("tau_rz", 0.0),
                "disp_z": r.get("disp_z", 0.0),
                "disp_r": r.get("disp_r", 0.0),
                "eps_z": r.get("eps_z", 0.0),
                "eps_r": r.get("eps_r", 0.0),
                "eps_t": r.get("eps_t", 0.0),
            }
            output_results.append(res_dict)

            disp_z = r.get("disp_z", 0.0)
            eps_t = r.get("eps_t", 0.0)
            eps_z = r.get("eps_z", 0.0)

            if abs(disp_z) > max_disp:
                max_disp = abs(disp_z)
            if abs(eps_t) > max_eps_t:
                max_eps_t = abs(eps_t)
            if abs(eps_z) > abs(max_eps_c):
                max_eps_c = eps_z

        return SolveResponse(
            status="success",
            results=output_results,
            max_disp=max_disp,
            max_strain_t=max_eps_t,
            max_strain_c=max_eps_c,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {e}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Solver resource missing: {e}")
    except Exception as e:
        logger.exception("Solver error: %s", e)
        raise HTTPException(status_code=500, detail="Solver failed. Check server logs.")


@app.post("/api/optimize", response_model=OptimizeResponse)
async def run_optimization(data: OptimizeRequest):
    try:
        logger.info("Received optimization request")

        # 1. Setup Input Objects
        traffic = TrafficInput(
            initial_aadt=0,
            commercial_vehicles_per_day=data.cvpd,
            traffic_growth_rate=data.growth_rate,
            design_life_years=data.design_life,
            lane_distribution_factor=data.lane_factor,
            vehicle_damage_factor=data.vdf,
        )

        subgrade = SubgradeInput(cbr=data.subgrade_cbr)

        # IRC:37-2018 §3.7 defines only R80 and R90 (the validator rejects
        # anything else). The optimizer further auto-escalates R80->R90 for
        # design traffic >= 20 msa.
        rel_map = {
            "80%": ReliabilityLevel.R80,
            "90%": ReliabilityLevel.R90,
        }
        reliability = rel_map.get(data.reliability, ReliabilityLevel.R90)

        # 2. Setup Problem
        l_types = [l.layer_type for l in data.layers if l.layer_type.lower() != "subgrade"]
        bounds = {}
        layer_props = {}
        for l in data.layers:
            layer_props[l.layer_type] = {'E': l.E, 'nu': l.nu}
            if getattr(l, 'geogrid', None):
                layer_props[l.layer_type]['geogrid'] = l.geogrid
            if l.is_fixed:
                bounds[l.layer_type] = (l.fixed_thickness, l.fixed_thickness)
            else:
                bounds[l.layer_type] = (l.min_thickness, l.max_thickness)

        # If caller provided explicit Subgrade E in layer_props AND also provided a
        # CBR value, prefer the CBR-derived modulus and drop the explicit E to
        # avoid conflicting intent (CBR is a higher-level geotechnical input).
        sub_custom = layer_props.get('Subgrade')
        if sub_custom and sub_custom.get('E') is not None:
            logger.warning("Optimize request provided Subgrade E while CBR is also set; preferring CBR-derived modulus and ignoring explicit Subgrade.E")
            # Remove only the explicit E override; keep any other subgrade props
            layer_props['Subgrade'] = {k: v for k, v in sub_custom.items() if k != 'E'}

        problem = OptimizationProblem(
            traffic=traffic,
            subgrade=subgrade,
            reliability=reliability,
            temperature=data.temperature,
            air_voids=data.air_voids,
            bitumen_volume=data.bitumen_volume,
            layer_types=l_types,
            layer_props=layer_props,
            thickness_bounds=bounds,
            material_rates=data.material_rates,
            wheel_load=data.wheel_load,
            tire_pressure=data.tire_pressure,
            wheel_type=data.wheel_type,
            wheel_spacing=data.wheel_spacing,
            ctb_axle_spectrum=[
                AxleLoadGroup(
                    axle_type=item.axle_type,
                    load_kn=item.load_kn,
                    expected_repetitions=item.expected_repetitions,
                ) for item in (data.ctb_axle_spectrum or [])
            ] or None,
            ctb_per_class_bridge_recompute=data.ctb_per_class_bridge_recompute,
            eval_points=[{"z": p.z, "r": p.r} for p in (data.points or [])] if data.points else None,
            optimize_by_cost=data.optimize_by_cost,
            optimize_by_co2=data.optimize_by_co2,
        )


        # 3. Run smart search in a thread with TWO layered timeouts:
        #    a) Optimizer-level deadline — the optimizer itself checks
        #       wall-clock between bridge calls and returns whatever
        #       adequate designs it has so far (graceful degradation).
        #    b) asyncio.wait_for hard ceiling — covers the case where the
        #       optimizer is stuck in a single bridge call. The bridge
        #       subprocess timeout (DEFAULT_BRIDGE_TIMEOUT_S = 30s)
        #       prevents that path from ever blocking forever.
        OPTIMIZER_BUDGET_S = 300.0   # 5-min wall-clock for the search
        HTTP_GRACE_S = 30.0          # extra grace for cleanup / final cost calc

        optimizer = SmartPavementSearch(problem)
        deadline = time.monotonic() + OPTIMIZER_BUDGET_S

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(optimizer.run, deadline=deadline),
                timeout=OPTIMIZER_BUDGET_S + HTTP_GRACE_S,
            )
        except asyncio.TimeoutError:
            # The optimizer's cooperative deadline should normally trigger
            # before this hard ceiling fires. Reaching this branch usually
            # means a single bridge call hung past its 30s subprocess
            # timeout — a real environment problem worth surfacing.
            raise HTTPException(
                status_code=504,
                detail=f"Optimization timed out after {OPTIMIZER_BUDGET_S + HTTP_GRACE_S:.0f}s",
            )

        # 4. Format Output: Return all adequate designs sorted by total thickness
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
                    # Cost & CO2 are returned only when their objective is
                    # enabled — they are only computed/shown for the Economy
                    # and Sustainable archetypes, which only appear then.
                    "cost": round(sol.cost, 0) if (data.optimize_by_cost and sol.cost is not None) else None,
                    "co2": round(sol.co2, 1) if (data.optimize_by_co2 and sol.co2 is not None) else None,
                    "details": _to_native(perf)
                })

        # Error list must be List[str] for the response schema; coerce any
        # non-string entries that may have been collected during evaluation.
        errors_out = None
        if data.debug:
            raw_errors = getattr(result, 'errors', None) or []
            errors_out = [str(e) for e in raw_errors]

        # Report geosynthetic reinforcement applied (geogrid + resulting MIF),
        # so the UI can show the sustainability lever in play.
        reinforcement_out = []
        from mep_opt.solver.geosynthetic import get_mif
        for l in data.layers:
            g = getattr(l, 'geogrid', None)
            if g:
                reinforcement_out.append({
                    "layer": l.layer_type,
                    "geogrid": g,
                    "mif": round(get_mif(subgrade.modulus, g), 3),
                })

        # IRC:SP:72 low-volume classification. Computed for every request so the
        # UI can switch framing below 2 MSA; advisory-only above it.
        from mep_opt.solver import sp72 as _sp72
        sp72_cls = _sp72.classify(
            cvpd=data.cvpd, vdf=data.vdf, growth_rate=data.growth_rate,
            design_life_years=data.design_life, lane_factor=data.lane_factor,
            cbr=data.subgrade_cbr,
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

        return OptimizeResponse(
            status="success",
            adequate_designs=adequate_designs_response,
            is_adequate=bool(result.is_feasible),
            errors=errors_out,
            warnings=list(getattr(result, 'warnings', None) or []),
            reinforcement=reinforcement_out,
            sp72=sp72_out,
        )

    except HTTPException:
        raise  # Re-raise timeout and other HTTP errors as-is
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {e}")
    except Exception as e:
        logger.exception("Optimization error: %s", e)
        raise HTTPException(status_code=500, detail="Optimization failed. Check server logs.")


# ---------------------------------------------------------------------------
# PDF Report Endpoint
# ---------------------------------------------------------------------------

class PdfReportRequest(BaseModel):
    project_name: str = "NH-Design-Session"
    traffic_params: dict
    subgrade_cbr: float
    selected_solution: dict
    adequate_designs: List[dict] = []


@app.post("/api/report/pdf")
async def generate_pdf_report(data: PdfReportRequest):
    try:
        from mep_opt.web.pdf_report import generate_report

        pdf_bytes = generate_report(
            project_name=data.project_name,
            traffic_params=_to_native(data.traffic_params),
            subgrade_cbr=data.subgrade_cbr,
            selected_solution=_to_native(data.selected_solution),
            adequate_designs=_to_native(data.adequate_designs),
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=IndoPave37_Report.pdf"}
        )
    except Exception as e:
        logger.error(f"PDF Generation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
