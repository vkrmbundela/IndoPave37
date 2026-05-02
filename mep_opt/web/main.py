"""
Flex Pave FastAPI Backend
=========================
Serves the web UI and provides analysis/optimization API endpoints.
"""

import asyncio
import logging
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from typing import List, Optional, Dict, Any
import numpy as np

from mep_opt.solver.legacy_bridge import run_bridge_from_stack, is_bridge_available
from mep_opt.optimizer.smart_search import SmartPavementSearch
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel
from mep_opt.web.knowledge_qa import IrcKnowledgeService, ChunkFilters

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Flex Pave")

# Add CORS middleware to support Vite React frontend
_raw_cors_origins = os.getenv(
    "MEP_OPT_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
_raw_extra_cors_origins = os.getenv("MEP_OPT_EXTRA_CORS_ORIGINS", "")

# Regex allows local dev origins on any port (e.g., Vite on 5173/5174/4173).
# Override via env if needed.
_cors_origin_regex = os.getenv(
    "MEP_OPT_CORS_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
).strip() or None

# Normalize configured origins (trim trailing slash to avoid exact-match misses).
_cors_origin_candidates = [
    *[o.strip() for o in _raw_cors_origins.split(",") if o.strip()],
    *[o.strip() for o in _raw_extra_cors_origins.split(",") if o.strip()],
]
_cors_origins = []
for _origin in _cors_origin_candidates:
    normalized = _origin.rstrip("/")
    if normalized not in _cors_origins:
        _cors_origins.append(normalized)
if not _cors_origins:
    _cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

_allow_all_origins = "*" in _cors_origins
if _allow_all_origins:
    _cors_origins = ["*"]
    # Regex is irrelevant when wildcard origins are enabled.
    _cors_origin_regex = None

logger.info(
    "CORS config: origins=%s origin_regex=%s",
    _cors_origins,
    _cors_origin_regex,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Advanced Engineering Modules (v2) — all routes under /api/v2/
from mep_opt.advanced.router import advanced_router
app.include_router(advanced_router)

# Mount Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)
templates = Jinja2Templates(directory=templates_dir)

# Local IRC corpus retrieval service (lazy-loaded on first request)
knowledge_service = IrcKnowledgeService()


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
    wheel_type: str = "Single"      # "Single" or "Dual"
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

    @field_validator("min_thickness")
    @classmethod
    def min_positive(cls, v):
        if v < 0:
            raise ValueError("min_thickness must be >= 0")
        return v

    @field_validator("max_thickness")
    @classmethod
    def max_positive(cls, v):
        if v <= 0:
            raise ValueError("max_thickness must be positive")
        return v


class OptimizeRequest(BaseModel):
    cvpd: float
    growth_rate: float
    design_life: int
    vdf: float = 2.5
    lane_factor: float = 0.75
    subgrade_cbr: float
    reliability: str = "90%"
    temperature: float = 35.0       # Pavement temperature (deg C)
    layers: List[LayerConstraint]

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

    @field_validator("reliability")
    @classmethod
    def valid_reliability(cls, v):
        valid = {"80%", "90%", "95%", "98%", "99%"}
        if v not in valid:
            raise ValueError(f"reliability must be one of {valid}")
        return v

class AdequateDesignSchema(BaseModel):
    optimal_layers: List[dict]
    total_thickness: float
    cost: float           # Informational only
    co2: float            # Informational only
    details: Optional[dict] = None

class OptimizeResponse(BaseModel):
    status: str
    adequate_designs: List[AdequateDesignSchema]
    is_adequate: bool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import math

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

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
        
        # 3. Solve via legacy bridge
        if not is_bridge_available():
            raise HTTPException(
                status_code=503,
                detail="Legacy bridge solver is not available. Ensure the reference executable is present.",
            )
        logger.info("Using legacy bridge solver")
        raw_results = run_bridge_from_stack(solver_stack, load_cfg, eval_points)

        # Adapt dict to object-like structure for the formatting loop
        class ResObj:
            def __init__(self, **entries):
                self.__dict__.update(entries)
        results = [ResObj(**r) for r in raw_results]

        # 6. Format Output
        output_results = []
        max_disp = 0.0
        max_eps_t = 0.0
        max_eps_c = 0.0

        for i, r in enumerate(results):
            res_dict = {
                "id": i,
                "z": data.points[i].z,
                "r": data.points[i].r,
                "sigma_z": getattr(r, "sigma_z", 0.0),
                "sigma_r": getattr(r, "sigma_r", 0.0),
                "sigma_t": getattr(r, "sigma_t", 0.0),
                "tau_rz": getattr(r, "tau_rz", 0.0),
                "disp_z": getattr(r, "disp_z", 0.0),
                "disp_r": getattr(r, "disp_r", 0.0),
                "eps_z": getattr(r, "eps_z", 0.0),
                "eps_r": getattr(r, "eps_r", 0.0),
                "eps_t": getattr(r, "eps_t", 0.0),
            }
            output_results.append(res_dict)

            if abs(r.disp_z) > max_disp:
                max_disp = abs(r.disp_z)
            if abs(r.eps_t) > max_eps_t:
                max_eps_t = abs(r.eps_t)
            if abs(r.eps_z) > abs(max_eps_c):
                max_eps_c = r.eps_z

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

        rel_map = {
            "80%": ReliabilityLevel.R80,
            "90%": ReliabilityLevel.R90,
            "95%": ReliabilityLevel.R95,
            "98%": ReliabilityLevel.R98,
            "99%": ReliabilityLevel.R99,
        }
        reliability = rel_map.get(data.reliability, ReliabilityLevel.R90)

        # 2. Setup Problem
        l_types = [l.layer_type for l in data.layers]
        bounds = {}
        layer_props = {}
        for l in data.layers:
            layer_props[l.layer_type] = {'E': l.E, 'nu': l.nu}
            if l.is_fixed:
                bounds[l.layer_type] = (l.fixed_thickness, l.fixed_thickness)
            else:
                bounds[l.layer_type] = (l.min_thickness, l.max_thickness)

        problem = OptimizationProblem(
            traffic=traffic,
            subgrade=subgrade,
            reliability=reliability,
            temperature=data.temperature,
            layer_types=l_types,
            layer_props=layer_props,
            thickness_bounds=bounds,
        )


        # 3. Run smart search in a thread with timeout
        optimizer = SmartPavementSearch(problem)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(optimizer.run),
                timeout=300.0,  # 5-minute safety cap
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Optimization timed out after 5 minutes")

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
                    "cost": round(sol.cost, 0),
                    "co2": round(sol.co2, 1),
                    "details": _to_native(perf)
                })

        return OptimizeResponse(
            status="success",
            adequate_designs=adequate_designs_response,
            is_adequate=bool(result.is_feasible)
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


class KnowledgeFiltersInput(BaseModel):
    page_min: Optional[int] = None
    page_max: Optional[int] = None
    heading_contains: Optional[str] = None
    has_equation: Optional[bool] = None


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    snippet_length: int = 480
    filters: Optional[KnowledgeFiltersInput] = None


class KnowledgeSearchHit(BaseModel):
    chunk_id: str
    page_start: int
    page_end: int
    heading: str
    has_equation: bool
    score: float
    snippet: str


class KnowledgeSearchResponse(BaseModel):
    status: str
    query: str
    total_chunks: int
    candidate_chunks: int
    matched_chunks: int
    returned_chunks: int
    results: List[KnowledgeSearchHit]


class KnowledgeAskRequest(BaseModel):
    query: str
    top_k: int = 4
    max_answer_chars: int = 900
    filters: Optional[KnowledgeFiltersInput] = None


class KnowledgeCitation(BaseModel):
    chunk_id: str
    page_start: int
    page_end: int
    heading: str
    score: float


class KnowledgeAskResponse(BaseModel):
    status: str
    query: str
    answer: str
    citations: List[KnowledgeCitation]
    retrieved_chunks: int


def _to_chunk_filters(filters: Optional[KnowledgeFiltersInput]) -> Optional[ChunkFilters]:
    if filters is None:
        return None

    if filters.page_min is not None and filters.page_max is not None:
        if filters.page_min > filters.page_max:
            raise ValueError("filters.page_min must be <= filters.page_max")

    return ChunkFilters(
        page_min=filters.page_min,
        page_max=filters.page_max,
        heading_contains=filters.heading_contains,
        has_equation=filters.has_equation,
    )


@app.post("/api/report/pdf")
async def generate_pdf_report(data: PdfReportRequest):
    from fastapi.responses import Response
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
            headers={"Content-Disposition": "attachment; filename=MEP_Report.pdf"}
        )
    except Exception as e:
        logger.error(f"PDF Generation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# IRC Knowledge Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_irc_knowledge(data: KnowledgeSearchRequest):
    """BM25-backed search over the local IRC corpus with metadata filters."""
    try:
        filters = _to_chunk_filters(data.filters)
        payload = await asyncio.to_thread(
            knowledge_service.search,
            data.query,
            data.top_k,
            filters,
            data.snippet_length,
        )

        # Hide full chunk text from the public API payload.
        for row in payload.get("results", []):
            row.pop("text", None)

        return KnowledgeSearchResponse(**payload)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Knowledge search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/knowledge/ask", response_model=KnowledgeAskResponse)
async def ask_irc_knowledge(data: KnowledgeAskRequest):
    """Return a lightweight extractive answer plus citations from local corpus."""
    try:
        filters = _to_chunk_filters(data.filters)
        payload = await asyncio.to_thread(
            knowledge_service.ask,
            data.query,
            data.top_k,
            filters,
            data.max_answer_chars,
        )
        return KnowledgeAskResponse(**payload)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Knowledge ask error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
