# IndoPave-37 — Pavement Design & Optimization Suite

IndoPave-37 is a high-performance pavement analysis, structural evaluation, and optimization platform aligned with **IRC:37-2019** (for highways) and **IRC:SP:72-2015** (for low-volume roads). It offers an interactive, premium **Zero-Scroll CAD-like dashboard** hosted directly in your web browser.

---

## 🌐 Live Web Application

Access the application instantly:
👉 **[IndoPave-37 Web Interface](https://vkrmbundela.github.io/IndoPave37/)**

---

## ⚙️ How the Software Works

IndoPave-37 operates using a hybrid engineering-optimization stack designed to find structural pavement designs that satisfy regulatory criteria while minimizing cost and carbon footprint:

### 1. Structural Solver
The software evaluates pavement designs using elastic layer theory. It determines critical strains under standard dual-wheel axle configurations:
* **Tensile Strain ($\varepsilon_t$)** at the bottom of the bituminous layer (fatigue).
* **Vertical Strain ($\varepsilon_v$)** at the top of the subgrade layer (rutting).

These computed strains are checked against the performance equations defined by **IRC:37-2019** to ensure adequate design life (under the target Cumulative Damage Factor).
* *Accuracy*: validated against the **IRC:37-2018 Annex-II worked examples** (Ex. II.3 flexible: ε_t 146 vs 146 µε, ε_v 245 vs 243 µε; Ex. II.4 CTB: σ_t 0.699 vs 0.700 MPa) and a **recorded run of the original IITPAVE** (all stresses/strains/deflection within ~1%). The TIHAN1 benchmark (mixed Poisson 0.35–0.45) deviates up to ~30%, a known limitation of the dual-wheel superposition; most cases are within a few percent.

### 2. Smart Pavement Search Optimizer
IndoPave-37 employs a deterministic **brute-force search** over constructable (MoRTH-aligned) layer thicknesses within the user's Min/Max bounds. It is exhaustive over the buildable design space — fully reproducible, with no local-minimum risk:
* **Enumerate & pre-filter**: every combination of standard construction lift sizes within bounds, minus those failing the IRC:37 / MoRTH minimum-thickness rules.
* **Evaluate**: each design through the native multi-layer elastic solver (ε_t at the bottom of the bottom bituminous layer; ε_v at the **top of the subgrade**), keeping designs with all IRC CDFs ≤ 1.0. Cost and embodied CO₂ are computed for each.
* **Four archetypes** are returned from the adequate set:
  * **Structural**: the thinnest adequate section (minimum material — the direct solver optimum).
  * **Economy**: the cheapest adequate section (minimum ₹/km).
  * **Sustainable**: the lowest embodied-carbon section (minimum kg CO₂/km).
  * **Premium**: the best *combined* optimum across thickness, cost and CO₂.
  When one design wins several objectives, its labels merge onto a single card (so you see 1–4 cards).

---

## 🖥️ How to Use the Web Application

> [!NOTE]
> For a comprehensive walkthrough of the multi-layer parameters, axle load settings, and advanced analysis tabs (such as 3D Strain Bulbs, Monte Carlo, Geogrids, and CTB spectra), please consult the detailed [IndoPave-37 Usage Guide](USAGE_GUIDE.md).

The zero-scroll engineering cockpit is split into interactive control, preview, and results panels:

### Step 1: Configure Pavement Layers
1. In the **Pavement Layers Grid**, you can add, remove, or modify layers.
2. For each layer, specify:
   * **Thickness** (mm) and its search limits (min/max boundaries).
   * **Elastic Modulus** (MPa) and **Poisson's Ratio**.
   * **Unit Cost** (per $m^3$) and **CO₂ Footprint** (per $m^3$) for environmental estimation.

### Step 2: Configure Axle Load & Design Parameters
In the parameters sidebar, configure your project specifics:
* **Design Traffic**: Set the design traffic loading in Million Standard Axles (MSA).
* **Reliability Level**: Select the target design reliability — **80% or 90%** (the only two levels defined by IRC:37-2018 §3.7). The optimizer auto-escalates 80% → 90% for design traffic ≥ 20 MSA.
* **Axle Configuration**: Define wheel loads, contact pressure, and coordinates for structural strain analysis.

### Step 3: Run the Optimizer
1. Under **Opt Target**, toggle whether to optimize by **Thickness**, **Cost**, or **Carbon Footprint (CO₂)**.
2. Click **Run Optimizer**.
3. The comparison charts and up to four archetype design cards (Structural, Economy, Sustainable, Premium) will populate instantly. Click on any archetype card to inspect its detailed layer layout and strain margins.

### Step 4: Explore Advanced Engineering Panels
Switch between the tabs at the bottom of the dashboard to run supplementary evaluations:
* **3D Strain Bulbs**: Visualizes the propagation of strain fields ($x$, $y$, $z$) beneath the dual wheels to identify high-stress concentration zones.
* **Monte Carlo Sensitivity**: Run stochastic evaluations on material properties and layer thicknesses to see probability distributions of pavement life.
* **Low Volume Roads (IRC:SP:72-2015)**: Switches parameters to design gravel, soil, and thin bituminous bases for rural corridors.
* **Geosynthetic Reinforcement**: Insert reinforcement grids to calculate the reduction in aggregate base thickness required.

### Step 5: Save & Export Your Project
* **Auto-Save**: The cockpit automatically saves your configuration locally.
* **Export Config**: Click **Export** to download your pavement project as a `.json` file.
* **Import Config**: Drag-and-drop or upload a previously exported configuration to resume your design work.
