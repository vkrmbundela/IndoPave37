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
The inputs sit in a rail of six numbered, collapsible sections on the left, with **Evaluate** (Ctrl+Enter) and **Optimize** (Ctrl+Shift+Enter) pinned to its foot. The results fill a bento canvas of tiles on the right, sized by importance. Below 1024 px the rail stacks above the canvas.
```
+--------------------------------------------------------------------------------------------+
| APP BAR: Use cases · Import · Export · PDF · Advanced · Help · IRC:37 · theme · Reset      |
+----------------------+---------------------------------------------+-----------------------+
| INPUT RAIL           | VERDICT: ring of the governing ratio,       | CROSS-SECTION         |
| 1 Pavement layers    | IRC-adequate / not, crust, one ring per     | (linked hover) and    |
| 2 Traffic · basis    | criterion (fatigue, rutting, CTB, long-life)| the analysed moduli   |
| 3 Bituminous mix     +----------------------+----------------------+                       |
| 4 Subgrade · load    | FATIGUE STRAIN et    | RUTTING STRAIN ev    |                       |
| 5 Design checks ·    | actual / allowable   | actual / allowable   |                       |
|   optimizer          +----------------------+----------------------+-----------------------+
| 6 Analysis points    | DESIGN TRAFFIC msa   | COST · CARBON        | CRUST COMPOSITION     |
|                      | + cumulative curve   | + share by layer     | (donut)               |
|                      +----------------------+----------------------+-----------------------+
|                      | STRAIN-DEPTH PROFILE: eh (tension +) and ev (compression +) against   |
|                      | depth over the layer bands, with the allowable and long-life limits   |
| [Evaluate][Optimize] +-----------------------------------------------------------------------+
|                      | RESULTS: archetype cards (ring, utilization bars, Inspect, Use) and    |
|                      | the trade-off bars; or the Evaluate point results                     |
+----------------------+-----------------------------------------------------------------------+
```
The verdict, strain, cost, crust and profile tiles show the evaluated trial section, or the optimized design picked with **Inspect**; before a run they show the design basis and the allowable strains.

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
In rail section **① Pavement layers**:
1. **Material**: `BC`, `DBM`, `BM`, `SDBC`, `SMA` (bituminous), `WMM`, `WBM`, `GSB`, `CRL` (granular), `CTB`, `CTSB` (cement treated) or `RAP` (stabilised RAP base).
2. **Mode**: `Fixed` thickness, or `Opt` with a min–max range for the optimizer. Evaluate analyses a range layer at its minimum. The chevron opens Poisson's ratio, the auto-modulus switch and the geogrid.
3. **Modulus E**: leave **Auto** on — granular layers follow IRC Eq. 7.1 on the effective modulus of the layers below; bituminous layers take the Table 9.2 value for the binder grade and pavement temperature. Switch Auto off to pin a tested value (IRC §9.2: it must not exceed Table 9.2). All bituminous layers are analysed with the bottom mix's modulus (§9.2), noted under the upper layers.
4. **IRC minimum**: the minimum thickness IRC enforces for the layer (e.g. WMM 150 mm §8.1, GSB 100 mm §7.2.2, crack-relief 100 mm §8.3); red when the layer is below it.
5. With a **CTB**, either keep a 100 mm aggregate crack-relief layer above it or switch on **SAMI over the CTB** (§8.3).

### Step 2: Traffic and design basis
In **② Traffic · design basis**:
* **Road category** sets the reliability (§3.7) and the CTB factor RF.
* **Carriageway** sets the lane distribution factor (§4.5.1); for a divided carriageway enter the CVPD of one direction (§4.6.1).
* **CVPD, growth, years to opening, design period, VDF**: the design traffic follows IRC Eq. 4.5/4.6. The **Table 4.2** button applies the indicative VDF of Table 4.2 (plain/hilly) when no axle-load survey exists. The design period is flagged when it is below §4.3.1.

In **③ Bituminous mix · climate**: binder grade of the bottom mix and the average annual pavement temperature (20–40 °C; about 35 °C in the plains) give the Table 9.2 modulus; Va and Vbe give the fatigue C factor.

In **④ Subgrade · load**: the subgrade CBR gives M<sub>RS</sub> (10 × CBR up to 5 %, 17.6 × CBR<sup>0.64</sup> above). The IRC standard axle (dual wheels, 20 kN each, 0.56 MPa, 310 mm) is the default and is flagged when changed.

### Step 3: Design limits
The **strain tiles** show the allowable fatigue and rutting strains for the design traffic (Eq. 3.1–3.4 solved for the strain), and the actual strains once the section is evaluated or optimized. In **⑤ Design checks · optimizer**, switch on **Long-life pavement** (§10) for 300 msa or more and for expressways: the optimizer then also keeps εt ≤ 80 µε and εv ≤ 200 µε.

### Step 4: Analysis points and Evaluate
**⑥ Analysis points** follows the IRC critical locations of the current stack by default: just above the bottom of the bituminous layer (and of a CTB) and just below the top of the subgrade, at r = 0 and between the duals. Editing a point switches this off; **IRC points** switches it back on. **Evaluate** gives the IRC verdict — fatigue and rutting damage against the current traffic — with the strain-depth profile, and flags the result when an input changes afterwards; the stresses and strains at every point are one click away under **Point results**.

### Step 5: Optimize
Set the layers to vary as `Opt`, choose the objectives in **⑤ Design checks · optimizer** (thickness always; cost and embodied CO₂ optional, with editable material rates) and click **Optimize**. Each archetype card shows the section, its governing ratio as a ring, its layer moduli, utilization bars for every IRC check, the critical strains against their allowable values, cost and carbon. **Inspect** shows a design in the verdict, strain, crust and profile tiles; **Use** copies it into the layer list. The trade-off tile compares the archetypes' crust, cost and carbon as bars.

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
* Applies a **Modulus Improvement Factor (MIF)** to the reinforced layer's Eq. 7.1 modulus (which rests on the effective modulus of the layers below, IRC:37-2018 §8.1), capped at **2.0** — the IRC:SP:59-2019 §3.1.3 design maximum for geogrids. SP:59 requires third-party-validated MIF for the actual product. A geogrid is accepted only on WMM/WBM/GSB, and not on an auto-modulus layer resting on a CTB/CTSB, whose modulus is a fixed IRC value. The reinforced section is analysed with separately estimated moduli, as IRC:37-2018 §7.2.3 / §8.1 prescribe. Each returned design is also compared with the conventional (unreinforced) section. When the geogrid does not lower the governing CDF, the design is flagged "no benefit" with a warning (SP:59 §3.1.3, steps 2 and 4).

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
