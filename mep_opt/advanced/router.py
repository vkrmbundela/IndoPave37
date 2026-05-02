"""
Advanced Engineering API Router (v2)
=====================================
All advanced endpoints live under /api/v2/ to avoid any
conflict with existing /api/solve, /api/optimize, /api/report/pdf.
"""

import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional

from .reserve import compute_reserve
from .materials_library import get_full_library, get_material_by_code
from .sensitivity import compute_sensitivity
from .strain_field import compute_strain_field
from .corridor import parse_corridor_csv, start_corridor_job, get_job_status
from .montecarlo import run_monte_carlo


advanced_router = APIRouter(prefix="/api/v2", tags=["advanced"])


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class LayerData(BaseModel):
    modulus: float
    poisson: float
    thickness: float
    name: Optional[str] = None
    friction_factor: float = 1.0

class LoadData(BaseModel):
    load: float = 20000
    pressure: float = 0.56
    is_dual: bool = True
    spacing: float = 310.0

class EvalPointData(BaseModel):
    z: float
    r: float

class ReserveRequest(BaseModel):
    eps_t: float
    eps_v: float
    mix_modulus: float
    design_msa: float
    reliability: int = 80
    air_voids: float = 4.0
    bitumen_volume: float = 11.5

class SensitivityRequest(BaseModel):
    layers: List[LayerData]
    load: LoadData
    eval_points: List[EvalPointData]
    cumulative_msa: float
    mix_modulus: float
    reliability: int = 80

class StrainFieldRequest(BaseModel):
    layers: List[LayerData]
    load: LoadData
    r_steps: int = 12
    z_steps: int = 25
    r_max: float = 500.0

class CorridorConstraint(BaseModel):
    layer_type: str
    min_thickness: float
    max_thickness: float
    E: float
    nu: float
    is_fixed: bool = False

class CorridorRequest(BaseModel):
    layer_constraints: List[CorridorConstraint]
    growth_rate: float = 0.05
    design_life: int = 20
    reliability: int = 80

class MonteCarloRequest(BaseModel):
    layers: List[LayerData]
    load: LoadData
    eval_points: List[EvalPointData]
    cumulative_msa: float
    mix_modulus: float
    sigmas: Optional[List[float]] = None
    n_simulations: int = 100
    reliability: int = 80

def _layers_to_dicts(layers: List[LayerData]) -> list[dict]:
    return [l.model_dump() for l in layers]

def _load_to_dict(load: LoadData) -> dict:
    return load.model_dump()

def _points_to_dicts(points: List[EvalPointData]) -> list[dict]:
    return [p.model_dump() for p in points]


# ---------------------------------------------------------------------------
# Module B: Structural Reserve Meter
# ---------------------------------------------------------------------------

@advanced_router.post("/reserve")
async def reserve_meter(req: ReserveRequest):
    """Compute structural capacity and reserve buffer."""
    try:
        result = compute_reserve(
            eps_t=req.eps_t, eps_v=req.eps_v,
            mix_modulus=req.mix_modulus, design_msa=req.design_msa,
            reliability=req.reliability, air_voids=req.air_voids,
            bitumen_volume=req.bitumen_volume,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module C: Material Library
# ---------------------------------------------------------------------------

@advanced_router.get("/materials")
async def list_materials():
    return {"status": "ok", "materials": get_full_library()}

@advanced_router.get("/materials/{code}")
async def get_material(code: str):
    mat = get_material_by_code(code)
    if mat is None:
        raise HTTPException(status_code=404, detail=f"Material '{code}' not found")
    return {"status": "ok", "material": mat}


# ---------------------------------------------------------------------------
# Module A: Sensitivity Heatmaps
# ---------------------------------------------------------------------------

@advanced_router.post("/sensitivity")
async def sensitivity_heatmap(req: SensitivityRequest):
    """Compute CDF sensitivity grid for each layer."""
    try:
        result = await asyncio.to_thread(
            compute_sensitivity,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            _points_to_dicts(req.eval_points),
            req.cumulative_msa,
            req.mix_modulus,
            req.reliability,
        )
        return {"status": "ok", "layers": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module D: 3D Strain Field
# ---------------------------------------------------------------------------

@advanced_router.post("/strain-field")
async def strain_field(req: StrainFieldRequest):
    """Compute strain values on an r-z grid for 3D visualization."""
    try:
        result = await asyncio.to_thread(
            compute_strain_field,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            req.r_steps,
            req.z_steps,
            req.r_max,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module E: Corridor Optimization
# ---------------------------------------------------------------------------

@advanced_router.post("/corridor")
async def corridor_upload(file: UploadFile = File(...)):
    """Upload a CSV and start async corridor optimization."""
    try:
        content = (await file.read()).decode("utf-8")
        sections = parse_corridor_csv(content)
        if not sections:
            raise HTTPException(status_code=400, detail="No valid sections in CSV")

        # Use default layer constraints (will be customizable later)
        default_constraints = [
            {"layer_type": "BC", "min_thickness": 30, "max_thickness": 50, "E": 1250, "nu": 0.35, "is_fixed": True},
            {"layer_type": "DBM", "min_thickness": 50, "max_thickness": 200, "E": 1250, "nu": 0.35, "is_fixed": False},
            {"layer_type": "WMM", "min_thickness": 150, "max_thickness": 300, "E": 300, "nu": 0.35, "is_fixed": False},
            {"layer_type": "GSB", "min_thickness": 150, "max_thickness": 300, "E": 200, "nu": 0.35, "is_fixed": False},
        ]
        job_id = await start_corridor_job(sections, default_constraints)
        return {"status": "ok", "job_id": job_id, "total_sections": len(sections)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@advanced_router.get("/corridor/{job_id}/status")
async def corridor_status(job_id: str):
    """Poll corridor optimization progress."""
    job = get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "ok", **job}


# ---------------------------------------------------------------------------
# Module F: Monte Carlo Risk Analysis
# ---------------------------------------------------------------------------

@advanced_router.post("/montecarlo")
async def monte_carlo(req: MonteCarloRequest):
    """Run Monte Carlo simulation with construction tolerances."""
    try:
        result = await asyncio.to_thread(
            run_monte_carlo,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            _points_to_dicts(req.eval_points),
            req.cumulative_msa,
            req.mix_modulus,
            req.sigmas,
            req.n_simulations,
            req.reliability,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
