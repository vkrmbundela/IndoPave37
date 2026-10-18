# IndoPave-37 Project Documentation

## Project Overview

**IndoPave-37** is a high-performance pavement analysis and optimization tool aligned with **IRC:37-2019**. It uses a **native Python multi-layer elastic (Burmister) solver** as its structural engine (the same algorithm IITPAVE implements) and a deterministic **Smart Search Optimizer** that produces four engineering archetypes (Structural, Economy, Sustainable, Premium). The zero-scroll **Engineering Cockpit Dashboard** provides interactive design exploration.

> **Solver note:** The original IIT Pave Fortran `.EXE` is **no longer used at runtime** — it has been replaced by an in-process Burmister solver (`mep_opt/solver/burmister.py`), which is what runs both on the backend and in the browser via Pyodide. The legacy-bridge modules are thin compatibility shims that route to the native solver. The native solver is validated against **IRC:37-2018 Annex-II worked examples** (see `mep_opt/tests/test_irc_annex.py`).

---

## Architecture & Technology Stack

- **Backend**: Python 3.10+ (**FastAPI**, Uvicorn)
- **Structural Solver**: **Native Python Burmister multi-layer elastic solver** (`burmister.py`, NumPy/SciPy) — in-process, thread-safe, no external executable. Runs identically on the backend and in-browser (Pyodide).
- **Numerical Support**: NumPy, SciPy
- **Frontend**: **React 19**, **Vite**, **Tailwind CSS v4**
- **Data Visualization**: **Recharts** (archetype comparison)
- **Optimization Engine**: **Smart Pavement Search** — deterministic brute-force enumeration of constructable lift sizes + four single-purpose archetypes (Structural / Economy / Sustainable / Premium). Exhaustive over the buildable space, no local-minimum risk, no external dependencies.
- **Legacy Bridge**: `iitpave_bridge.py` / `legacy_bridge.py` are compatibility shims that route all calls to the native Burmister solver (`solver_facade.py`). No Fortran `.EXE` is invoked.
- **Engine duplication**: the in-browser (Pyodide) build uses a mirrored copy of the engine under `frontend/public/py/mep_opt/`, plus a top-level `frontend/public/py/burmister.py` used by the browser Evaluate path. Copy every changed engine module to its mirror (`tools/` is git-ignored, so there is no committed sync script); `mep_opt/tests/test_backend_sync.py` fails if any copy drifts.

---

## UI/UX & Design System

The platform follows a premium **Industrial Blueprint** aesthetic:
- **Themes**:
  - **Slate Engineering** (Light): High-contrast, matte white/slate corporate style.
  - **Antigravity** (Dark): Deep indigo/slate theme for technical clarity.
- **Typography**: **Poppins** (Headlines & UI elements) paired with **Inter** for data/labels.
- **Layout**: **Bento cockpit** — a dense grid of tiles (`src/cockpit/`: `Tile`, `Kpi`, `UtilBar`, `Chip`, `Notice`, `Seg`, `Field`, `Toggle`; design cards and comparison), each carrying live engineering data: layer structure (with the IRC minimum per layer), cross-section (linked hover, resizable), traffic & design basis (§4.5.1 LDF by carriageway, Table 4.2 VDF), bituminous mix & climate (Table 9.2 modulus by binder and temperature), load & subgrade, design limits (allowable strains, long-life), optimizer objectives, analysis points (one-click IRC critical points) and results (Evaluate verdict with CDF bars; archetype cards with utilization bars and a comparison tile).
- **Themes in code**: light is the default; the app-bar toggle sets `.theme-dark` on `<html>` (per viewer, `localStorage`). New components use the `index.css` tokens; under `.theme-dark` the Tailwind palette variables are re-mapped, so existing `bg-white` / `text-gray-*` markup also renders dark. Component classes live in `@layer components` so utilities on the same element win.
- **Persistence**: Hybrid `localStorage` sync with auto-save and two-stage Reset safety (export-to-JSON).

---

## Optimization Algorithm

The optimizer (`SmartPavementSearch` in `optimizer/smart_search.py`) is a **deterministic brute-force lift enumeration with Pareto selection** — not a greedy/gradient search. It is exhaustive over a small, constructable design space, so it is fully reproducible and free of local-minimum risk.

**Step 1 — Enumerate constructable combinations.**
For each layer, take the discrete *constructable lift sizes* (MoRTH-500-aligned `DEFAULT_LIFT_SCHEDULE`, or a user override) that fall within the layer's thickness bounds. Form the Cartesian product. A typical 4-layer stack yields ~100–300 combinations (a warning fires above 50k).

**Step 2 — IRC / MoRTH pre-filter.**
Drop combinations that violate minimum thicknesses *before* any solver call. IRC:37-2018 rules are always enforced (CTB > 20 msa → bituminous bundle ≥ 100 mm, §9.2; unbound granular base WMM/WBM ≥ 150 mm and crack-relief layer ≥ 100 mm, §8.1; GSB ≥ 100 mm, §7.2.2; CTB ≥ 100 mm, §8.2.1; stabilised RAP base ≥ 100 mm, §8.4). The CTSB 200 mm of §7.3.1 is only recommended and is not enforced. When no combination survives, the message names every rule that removed one (mandatory or traffic-tier), and the preliminary design obeys the mandatory rules. The traffic-tier MoRTH-practice minimums can be overridden or disabled (`ignore_minimum_thickness`). Combinations are then sorted by ascending total thickness (or ₹/km when `optimize_by_cost`).

**Step 3 — Evaluate each design** through the native Burmister solver:
- `eps_t` (fatigue) at the **bottom of the bottom bituminous layer**: the largest TENSILE value of εt/εr at r = 0 and 155 mm (Annex II/III). When every component is compressive, fatigue is not checked (Annex III, `fatigue_compressive`), and the compressive value is reported as a negative number;
- `eps_v` (rutting) at the **top of the subgrade** (just below the granular/subgrade interface) per IRC:37-2018 §3.6.1;
- CTB fatigue at the bottom of the CTB (not a CTSB) at 0.80 MPa: Eq. 3.5 on the largest |ε| (RF = 1 for Expressway/NH/SH/urban roads or ≥ 10 msa, else 2) and, with an axle spectrum, Eq. 3.6/3.7 on the largest |σ| of the radial/tangential components — every class solved exactly, tandems/tridems split into 2/3 single axles, wheel load = single-axle load / 4 (Annex-II II.4).
Strains/stresses enter the performance equations as magnitudes (IRC Table 3.1 note (a)); the sign only decides whether bituminous fatigue applies. With an axle spectrum, a design that already fails another criterion skips the per-class CTB solves (CDF_ctb is then the Eq. 3.5 lower bound); the infeasibility diagnostic completes those before ranking (only the wall-clock deadline can stop it, and then the CDF is reported as a lower bound). A geogrid-reinforced section is analysed as IRC prescribes for reinforced layers: moduli estimated separately, with the MIF on top (§7.2.3 / §8.1, the IRC:SP:59 §3.1.3 step-6 check; the cockpit uses the same moduli). Every returned design of an all-unbound reinforced stack is also compared with the conventional §7.2.3 section (SP:59 steps 2 and 4). It is flagged `geogrid_credit: "no benefit"`, with a warning, when the geogrid does not lower the governing CDF. Geogrid placement is validated before the search: only WMM/WBM/GSB, and not on an auto-modulus layer resting on CTB/CTSB. A design is **adequate** when all applicable CDFs (fatigue + rutting + CTB) ≤ 1.0. With `long_life` (IRC §10 / Annex II.6, recommended from 300 msa and for expressways, §4.3.1) it must also keep the bituminous tensile strain ≤ 80 µε and the subgrade strain ≤ 200 µε (`details.long_life` carries the ratios; `governing_mode` may be `long_life`). `has_sami` (§8.3) accepts a bituminous layer directly on a CTB (the SAMI is not a structural layer). Reliability is R90 for Expressway/NH/SH/urban roads at any traffic and for other roads at ≥ 20 msa (IRC §3.7, `road_category`); the fatigue C-factor uses the bottom-mix `Va`/`Vbe`.

**Step 4 — Four archetypes.**
From the IRC-adequate set (cost and embodied CO₂ are computed for every design), return four single-purpose optima:
- **Structural** — thinnest adequate design (minimum total material; the direct solver optimum);
- **Economy** — cheapest adequate design (minimum ₹/km);
- **Sustainable** — greenest adequate design (minimum embodied CO₂/km);
- **Premium** — best *combined* optimum: minimises the equally-weighted, min-max-normalised sum of thickness + cost + CO₂.

When one design wins several objectives, its labels merge onto a single card (e.g. "Economy + Sustainable"), so the UI shows 1–4 cards — exactly as many as there are genuinely distinct optimal strategies. A cooperative wall-clock deadline returns the best designs found so far if the budget is exceeded.

---

## Solver Accuracy & Validation

Validated against **IRC:37-2018 Annex-II worked examples**, a recorded run of the original IITPAVE, and legacy benchmark cases (rps1, case2):
- **Example II.3** (flexible, 131 MSA): native `eps_t` = 146 µε vs IRC 146 (−0.0%); `eps_v` = 245 µε vs IRC 243 (+0.7%).
- **Example II.4** (CTB): native max tensile stress at CTB bottom = 0.699 MPa vs IRC 0.700; all 12 single-axle class stresses match the IRC table and their damage is 0.48 as published.
- **Examples II.1 / II.2 / II.5**: effective modulus 105.0 vs 105.1 MPa; GSB strains within 0.4%; RAP-base εt 104.1 vs 104.2 µε (IRC's quoted εv for II.5 is the strain at the top of the CTSB).
- **Near-surface**: exact against Boussinesq at z = 0 and at every depth ≥ 0.5 mm (top-layer half-space kernel subtracted and integrated in closed form / densely; refined panels for shallow points). Points shallower than 0.5 mm, which is below the continuum scale of a bituminous layer, are evaluated at the surface, and the result reports z = 0. Far-field points (r > 4a) use the refined panels at every depth. The coefficient systems are solved batched over the Hankel nodes, matching the scalar solve to 1e-10.
- **Input domain**: finite layers ≥ 1 mm (0 = omitted, keeping its interface bond); evaluation points finite, z ≥ 0, |r| ≤ 20 m (r is a radius, so its sign is ignored). The API rejects NaN / Infinity in every request (422, also in the browser bridges), and the pavement temperature must be 20–40 °C (the IRC:37-2018 Table 9.2 range).
- **Annex II.6 (long-life)**: Solutions 1–3 give εt 80.0 / 79.2 / 77.8 µε and εv 154 / 158 / 173 µε against IRC's 80 / 80 / 78 and 153 / 157 / 172 (`test_long_life_sami.py`); Solution 1 passes with IRC's rounded M<sub>RS</sub> = 62 MPa (80.01 µε at CBR 7 exactly).
- **Annex III**: bituminous fatigue strain 118 / 34.8 µε (Tables III.2 / III.4) against IRC's 1.18E-04 / 3.48E-05; the SAMI section of Table III.3 is compressive (−66 µε), so fatigue is not checked.
- **Recorded IITPAVE run**: all stresses, strains and deflection match within ~1% (`mep_opt/tests/test_iitpave_reference.py`).
- **Compliance**: Automated adequacy checks against IRC:37-2018/2019 fatigue, rutting, and CTB performance equations. Regression suite: `mep_opt/tests/test_irc_annex.py`.

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

# Audit regression suites (exact solutions, IRC Annex-II/III examples, verification round 2)
python -m pytest mep_opt/tests/test_audit_fixes.py mep_opt/tests/test_audit_round2.py mep_opt/tests/test_audit_round3.py -v
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
|   |   +-- iitpave_bridge.py # Compat shim → native Burmister solver (no .EXE)
|   |   +-- legacy_bridge.py  # Public API surface for bridge
|   |   +-- irc37.py          # IRC:37-2019 Design Equations
|   |   +-- materials.py      # Material property database
|   +-- optimizer/
|   |   +-- smart_search.py   # Brute-force lift enumeration + 4 archetypes
|   |   +-- problem.py        # Problem/Result data structures
|   +-- cost/                  # Cost & CO2 (LCA) estimation
|   +-- advanced/              # Sensitivity, Monte Carlo, Strain Field, Corridor
|   +-- web/
|       +-- main.py            # FastAPI Endpoints & CORS
+-- CLAUDE.md                  # This Documentation
```

---

## Core Development Guidelines

1. **Design Integrity**: All new components must support both `light` (default) and `.theme-dark` CSS classes. Use the centralized design tokens in `index.css`.
2. **Solver Dependency**: All structural analysis runs through the native Python Burmister solver (`solver_facade.run_solver`). No external `.EXE` is required on any machine. The browser (Pyodide) build uses the mirrored engine under `frontend/public/py/mep_opt/` (plus the top-level `frontend/public/py/burmister.py`) — copy every engine change to its mirror; `test_backend_sync.py` enforces it.
3. **Mathematical Accuracy**: Any solver or IRC logic change must be regression-tested against the IRC Annex-II suites (`test_irc_annex.py`, `test_audit_fixes.py`) and the benchmark suite (`test_solver.py`). Critical conventions: `eps_v` at top of subgrade (below the interface); `eps_t` = largest tensile strain at bottom of bottom bituminous layer (all compressive → fatigue not checked, Annex III); all bituminous layers analysed with the bottom-mix modulus (§5/§9.2) — in the optimizer, in Evaluate and in the advanced panels (`applyBundleModulus` in `irc.js`); granular modulus uncapped Eq. 7.1 on the *effective* modulus of everything below (composite for all-unbound stacks, §7.2.3, with the thickness-weighted ν); granular base over CTSB 350/300 MPa, crack-relief layer over CTB 450 MPa, RAP base 800 MPa; geogrid MIF capped at 2.0 (IRC:SP:59 §3.1.3); subgrade ν = 0.35; dual-wheel standard axle.
4. **Optimized Responses**: Ensure all API responses handle NumPy types correctly using `_to_native()` serialization (NaN/Inf converted to null).
5. **Input Validation**: All API endpoints use Pydantic `field_validator` constraints. Bad inputs return 422 with specific messages.
6. **No Placeholders**: Use real data or generated assets for all engineering demonstrations.
