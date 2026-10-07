# IndoPave-37 — Pavement Design & Optimization Suite
## Professional Operations Manual & User Guide

Welcome to the **IndoPave-37** Operations Manual. IndoPave-37 is a mechanistic-empirical pavement design, analysis, and optimization suite designed in accordance with **IRC:37-2019** (Highways) and **IRC:SP:72-2015** (Low-Volume Roads). 

This guide outlines the system's architecture, user interface, step-by-step design procedures, and advanced analysis tools.

---

## 1. Interface & Design System Overview
IndoPave-37 features a single-page, **Zero-Scroll CAD Cockpit** designed for desktop engineering workflows. It adapts dynamically to two theme modes:
* **Slate Engineering (Light)**: High-contrast, matte-white layout optimized for daylight engineering environments.
* **Antigravity (Dark)**: Deep indigo/slate layout designed to reduce eye strain during technical analysis.

### Dashboard Layout
```
+--------------------------------------------------------------------------------+
|  HEADER: App Title, Run Solver / Run Optimizer Buttons, Import / Export JSON   |
+----------------------+---------------------------------------------------------+
|                      |  MIDDLE: Pavement Layers Grid (Material, Modulus,       |
|  LEFT:               |          Thickness, Min/Max Limits, Cost, Carbon, etc.) |
|  Settings Panel      +---------------------------------------------------------+
|  - Traffic (MSA)     |  RIGHT:                                                 |
|  - Subgrade CBR      |  CAD Blueprint Visualizer (SVG)                         |
|  - Temp (°C)         |  - Layer dimension chains & ruler depth                 |
|  - Axle Specs        |  - Dual/Single tires, axles, load badges, stress bulbs  |
|                      |  - Interactive green targets (analysis points)          |
+----------------------+---------------------------------------------------------+
|  BOTTOM: Output Results (Structural, Economy, Sustainable, Premium cards),     |
|          Archetype Comparison Charts, and Advanced Feature Tabs                |
+--------------------------------------------------------------------------------+
```

---

## 2. Pavement Structural Solver (Mechanistic Analysis)

IndoPave-37 uses elastic layer theory to model multi-layered systems. The bottom-most layer (Subgrade) is modeled as a semi-infinite elastic half-space, while all upper layers have finite thicknesses.

### Primary Design Failure Criteria (IRC:37-2019)
The suite calculates and checks design safety against two critical failure modes:
1. **Bituminous Fatigue Cracking**: Caused by horizontal tensile strain ($\varepsilon_t$) at the bottom of the lowest bituminous layer. The engine takes the largest *tensile* value of the tangential and radial strains under the dual wheels; when they are all compressive (thin layers on strong bases), fatigue is not checked, as in IRC:37-2018 Annex III.
2. **Subgrade Rutting**: Caused by vertical compressive strain ($\varepsilon_v$) at the top of the subgrade.

### Reference Validation
IndoPave-37's structural engine is validated against the **IRC:37-2018 Annex-II worked examples** (Ex. II.3 flexible, Ex. II.4 CTB) and a **recorded run of the original IITPAVE** — all stresses, strains and deflection match within **~1%**:
* **IRC Ex. II.3**: ε_t 146 vs 146 µε; ε_v 245 vs 243 µε.
* **IRC Ex. II.4 (CTB)**: σ_t 0.699 vs 0.700 MPa.
* **RPS1 / Case2 benchmarks**: thin and thick bituminous sections.

---

## 3. Step-by-Step Pavement Design Workflow

### Step 1: Configure Layer Structure
In the **Pavement Layers Grid**, you can define your trial layers.
1. **Material Type**: Classify the layer (e.g., `BC` (Bituminous Concrete), `DBM` (Dense Bituminous Macadam), `WMM` (Wet Mix Macadam), `GSB` (Granular Sub-base), or `CTB` (Cement Treated Base)).
2. **Thickness ($h$)**: Specify the current thickness in millimeters. 
3. **Modulus ($E$)**: Set the Elastic Modulus of the material in Megapascals (MPa).
4. **Poisson's Ratio ($\nu$)**: Define the lateral-to-longitudinal strain ratio (typically `0.35` for bituminous/granular layers, `0.20` for CTB, `0.35` or `0.40` for soil).
5. **Cost & Carbon ($CO_2$)**: Fill in unit costs and CO₂ footprints per cubic meter to compute cost and sustainability metrics during optimization.

### Step 2: Establish Design Traffic & Environmental Parameters
In the left sidebar, configure:
* **Design Traffic (MSA)**: Cumulative Standard Axles expected over the design life.
* **Subgrade CBR (%)**: California Bearing Ratio. The software automatically computes the Resilient Modulus ($M_{RS}$) using the IRC formula:
  * For CBR $\le 5$: $M_{RS} = 10 \times CBR$
  * For CBR $> 5$: $M_{RS} = 17.6 \times CBR^{0.64}$
* **Temperature (°C)**: Used to adjust temperature-dependent VG-graded bituminous mixes.

### Step 3: Define Load & Configuration Details
Under **Axle Configuration**:
* **Wheel Type**: Toggle between `Single` or `Dual` wheel sets.
* **Load (N)**: Enter the wheel load. The default `20,000 N` represents one wheel set of a standard 80 kN axle distributed across 4 wheels (half-axle load of 40 kN divided by 2 wheels).
* **Tyre Pressure (MPa)**: Tyre inflation pressure (typically `0.56 MPa` for highway axle loads, and `0.80 MPa` for heavy load/CTB spectrums).
* **Wheel Spacing (mm)**: Center-to-center distance of the dual wheels (default `310 mm`).

### Step 4: Configure Analysis Points
The **Analysis Points Grid** defines the coordinate offsets where strains are evaluated:
* **Radial Offset ($r$)**: Radial distance from the wheel center (mm). Use `0 mm` for directly under one wheel and `155 mm` for halfway between dual wheels.
* **Depth ($z$)**: Depth in millimeters from the surface. The system evaluates points at the bituminous-granular interface and granular-subgrade interface to check fatigue and rutting constraints.

### Step 5: Choose Optimization Targets & Run
Under **Opt Target**:
1. Check **Thickness**, **Cost**, or **Carbon Footprint (CO₂)** to specify optimization priorities.
2. Under the layers grid, set **Min/Max Thickness Limits** for layers you wish to optimize. Uncheck "Fixed" to allow the optimizer to adjust those thicknesses.
3. Click **Run Optimizer**.

---

## 4. Understanding Optimization Archetypes
The deterministic **Smart Pavement Search** enumerates every constructable (MoRTH-aligned) lift combination within your Min/Max bounds, keeps the IRC-adequate ones, and returns up to four single-purpose optima. When one design wins several objectives, its labels merge onto a single card (so you may see 1–4 cards):

| Archetype Card | Description | Optimization Focus |
| :--- | :--- | :--- |
| 🔵 **Structural** | The thinnest adequate pavement layout — the direct minimum-material result. | Minimum total thickness / excavation depth. |
| 💰 **Economy** | The cheapest adequate layout (minimum ₹/km) at your material unit rates. | Lowest initial capital cost. |
| 🍀 **Sustainable** | The lowest embodied-carbon adequate layout (minimum kg CO₂/km). | Lowest carbon footprint. |
| 🏆 **Premium** | The best *combined* optimum — jointly minimises thickness, cost and CO₂. | Best all-round balance of the three objectives. |

*Click on any card to automatically load that design configuration directly onto the visualizer and active editor grid.*

---

## 5. Advanced Cockpit Features

### 📊 3D Strain Bulbs Viewer
Visualizes the propagation of stresses and strain fields ($x$, $y$, $z$) underneath the wheel loads.
* Use this to identify localized shear stresses at the interfaces.
* The visualizer maps three-dimensional pressure cones (stress bulbs) to verify where vertical stresses dissipate.

### 🎲 Monte Carlo Sensitivity Analysis
Run probabilistic risk evaluations using statistical variations.
* Set standard deviations for layer thicknesses ($h$) and resilient moduli ($E$).
* The simulation runs 200+ structural iterations to calculate the probability distribution of pavement life, helping you design against material variation and construction tolerances.

### 🌾 Low-Volume Roads (IRC:SP:72-2015)
Switches the design engine to low-volume pavement rules.
* Automatically maps traffic to SP:72 categories (`T1` through `T9`).
* Calculates structural requirements for gravel bases, soil bases, and thin bituminous seals.

### 🕸️ Geosynthetic Base Reinforcement (Geogrids)
Integrate geogrid interlayers to reduce required base thickness.
* Granular base/sub-base layers allow selection of biaxial or triaxial geogrids.
* Applies a **Modulus Improvement Factor (MIF)** to the reinforced layer's Eq. 7.1 modulus (which rests on the effective modulus of the layers below, IRC:37-2018 §8.1), capped at **2.0** — the IRC:SP:59-2019 §3.1.3 design maximum for geogrids. SP:59 requires third-party-validated MIF for the actual product. A geogrid is accepted only on WMM/WBM/GSB, and not on an auto-modulus layer resting on a CTB/CTSB, whose modulus is a fixed IRC value. The optimizer also checks the conventional (unreinforced) section and keeps whichever is less critical, so a geogrid can never make a design thicker (SP:59 §3.1.3).

### 🚒 Cement Treated Base (CTB) Axle Spectrum
When designing with a Cement Treated Base:
1. Turn on **CTB Axle Spectrum** to perform a Cumulative Fatigue Damage (CFD) analysis.
2. Enter the expected **Axle Load Spectrum** (JSON array of axle groups detailing `axle_type` (single/tandem/tridem), `load_kn`, and expected repetitions).
3. The engine performs stress ratio analysis against the Modulus of Rupture ($M_{R} \approx 1.4\text{ MPa}$) to calculate cumulative fatigue damage ($CFD \le 1.0$) across all axle categories.

---

## 6. Saving & Exporting Designs
* **Auto-Save**: The application saves your current project configurations, active selections, and resized splitter layout to `localStorage` on every change.
* **Export Project (JSON)**: Click **Export** to download a `.json` configuration file containing all active layer properties, cost catalogs, and parameters.
* **Import Project**: Drag-and-drop or click **Import** to load a saved project file and resume work.
* **Reset**: Offers a two-stage safety reset. Resetting allows you to download your current design before clearing the cockpit cache.

---

## 7. Developer & Hosting Guidelines
If you are running or developing the suite locally:
* **Backend Run**: Use `python -m mep_opt.web.main` (runs on `http://127.0.0.1:8000`).
* **Frontend Run**: Run `cd frontend && npm run dev` (runs on `http://localhost:5173`).
* **Serverless / Browser-Only Mode**: In production, IndoPave-37 runs 100% serverless using **Pyodide** inside a Web Worker. This loads and executes the Python solver package directly inside the browser client.
