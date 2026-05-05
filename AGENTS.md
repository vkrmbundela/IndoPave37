# Flex Pave Project Documentation

## Project Overview

**Flex Pave** is a high-performance pavement analysis and optimization tool aligned with **IRC:37-2019**. It uses the **IIT Pave legacy executable** as its structural solver and a deterministic **Smart Search Optimizer** that produces three engineering archetypes (Economy, Balanced, Premium). The zero-scroll **Engineering Cockpit Dashboard** provides interactive design exploration.

---

## Architecture & Technology Stack

- **Backend**: Python 3.10+ (**FastAPI**, Uvicorn)
- **Structural Solver**: **IIT Pave legacy executable** (Fortran) via bridge module — thread-safe `.IN/.OUT` file I/O
- **Numerical Support**: NumPy, SciPy
- **Frontend**: **React 19**, **Vite**, **Tailwind CSS v4**
- **Data Visualization**: **Recharts** (archetype comparison)
- **Optimization Engine**: **Smart Pavement Search** — hybrid greedy climb + targeted grid sweep. Deterministic, no external dependencies.
- **Legacy Bridge**: `iitpave_bridge.py` module for executing and parsing the IIT Pave reference executable.

---

## UI/UX & Design System

The platform follows a premium **Industrial Blueprint** aesthetic:
- **Themes**:
  - **Slate Engineering** (Light): High-contrast, matte white/slate corporate style.
  - **Antigravity** (Dark): Deep indigo/slate theme for technical clarity.
- **Typography**: **Poppins** (Headlines & UI elements) paired with **Inter** for data/labels.
- **Layout**: **Zero-Scroll Cockpit** with draggable splitters for a CAD-like experience, high-density data cards, and interactive cross-section previews.
- **Persistence**: Hybrid `localStorage` sync with auto-save and two-stage Reset safety (export-to-JSON).

---

## Optimization Algorithm

The optimizer uses a two-phase deterministic search:

**Phase 1 — Greedy Climb** (~80-200 IIT Pave calls):
Start from minimum layer thicknesses. Increment the cheapest layer by 5mm each step until the first IRC:37-adequate design is found.

**Phase 2 — Boundary Sweep** (~200-2000 IIT Pave calls):
Grid-search all 5mm-step combinations within a +/-20mm window around the Phase 1 result. Sorted by ascending total thickness with early termination. Collects adequate designs for three archetypes:
- **Economy**: thinnest adequate design
- **Premium**: lowest CDF (maximum safety margin)
- **Balanced**: closest to midpoint in normalized (thickness, CDF) space

Every evaluation calls the IIT Pave `.EXE` through the legacy bridge for structural analysis.

---

## Solver Accuracy & Validation

Validated against legacy benchmark cases (rps1, case2, TIHAN1):
- Vertical strain (`eps_v`) and Tensile strain (`eps_t`) accuracy is within **<1-2%** of legacy outputs.
- **Compliance**: Automated adequacy checks against IRC:37-2019 fatigue and rutting performance equations.

---

## Commands & Usage

### 1. Build & Installation

```bash
# Backend Setup
python -m venv venv
.\venv\Scripts\activate
pip install -r mep_opt/requirements.txt

# Frontend Setup
cd frontend
npm install
```

### 2. Running Locally

You must run both the backend and frontend in separate terminals:

**Terminal 1 (Backend)**:
```bash
python -m mep_opt.web.main
```
*Runs on `http://127.0.0.1:8000`*

**Terminal 2 (Frontend)**:
```bash
cd frontend
npm run dev
```
*Runs on `http://localhost:5173`*

### 3. Testing 

```bash
# Backend Test Suite
python -m pytest mep_opt/tests/ -v

# Standalone Solver Validation
python tests/validate_solver.py
```

---

## File Structure

```
+-- frontend/                # React (Vite/Tailwind v4) Dashboard
|   +-- src/
|   |   +-- App.jsx          # Main Dashboard logic & State
|   |   +-- index.css        # Design tokens & Themes
|   +-- vite.config.js       # Tailwind configuration
+-- mep_opt/                 # Core Python Backend
|   +-- solver/
|   |   +-- iitpave_bridge.py # IIT Pave executable bridge (thread-safe)
|   |   +-- legacy_bridge.py  # Public API surface for bridge
|   |   +-- irc37.py          # IRC:37-2019 Design Equations
|   |   +-- materials.py      # Material property database
|   +-- optimizer/
|   |   +-- smart_search.py   # Hybrid greedy + grid search optimizer
|   |   +-- problem.py        # Problem/Result data structures
|   +-- cost/                  # Cost & CO2 (LCA) estimation
|   +-- advanced/              # Sensitivity, Monte Carlo, Strain Field, Corridor
|   +-- web/
|       +-- main.py            # FastAPI Endpoints & CORS
+-- AGENTS.md                  # This Documentation
```

---

## Core Development Guidelines

1. **Design Integrity**: All new components must support both `light` (default) and `.theme-dark` CSS classes. Use the centralized design tokens in `index.css`.
2. **Solver Dependency**: All structural analysis runs through the IIT Pave legacy bridge. The `.EXE` must be present on the deployment machine.
3. **Mathematical Accuracy**: Any solver or IRC logic changes must be regression-tested against the baseline benchmark suite.
4. **Optimized Responses**: Ensure all API responses handle NumPy types correctly using `_to_native()` serialization (NaN/Inf converted to null).
5. **Input Validation**: All API endpoints use Pydantic `field_validator` constraints. Bad inputs return 422 with specific messages.
6. **No Placeholders**: Use real data or generated assets for all engineering demonstrations.
