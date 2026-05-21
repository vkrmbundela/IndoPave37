# FlexPave — Pavement Design & Optimization Suite

FlexPave is a high-performance pavement analysis, structural evaluation, and optimization platform aligned with **IRC:37-2019** (for highways) and **IRC:SP:72-2015** (for low-volume roads). It offers an interactive, premium **Zero-Scroll CAD-like dashboard** hosted directly in your web browser.

---

## 🌐 Live Web Application

Access the application instantly:
👉 **[FlexPave Web Interface](https://vkrmbundela.github.io/flex-pave/)**

---

## ⚙️ How the Software Works

FlexPave operates using a hybrid engineering-optimization stack designed to find structural pavement designs that satisfy regulatory criteria while minimizing cost and carbon footprint:

### 1. Structural Solver
The software evaluates pavement designs using elastic layer theory. It determines critical strains under standard dual-wheel axle configurations:
* **Tensile Strain ($\varepsilon_t$)** at the bottom of the bituminous layer (fatigue).
* **Vertical Strain ($\varepsilon_v$)** at the top of the subgrade layer (rutting).

These computed strains are checked against the performance equations defined by **IRC:37-2019** to ensure adequate design life (under the target Cumulative Damage Factor).
* *Accuracy*: FlexPave is validated to produce strain and deflection results within **<1-2% deviation** compared to classical pavement benchmarks (e.g., RPS1, Case2, and TIHAN1).

### 2. Smart Pavement Search Optimizer
Instead of running arbitrary heuristics, FlexPave employs a deterministic, two-phase grid-search algorithm:
* **Phase 1 (Greedy Climb)**: Starting from minimum thickness limits, it iteratively increments the thickness of the most cost-effective layer by 5mm until the design first satisfies IRC:37 adequacy.
* **Phase 2 (Boundary Sweep)**: It sweeps all 5mm combinations within a window around the Phase 1 result to identify all adequate alternatives, compiling three engineering archetypes:
  * **Economy**: The thinnest adequate pavement structure.
  * **Balanced**: The midpoint design offering the best trade-off between total thickness, cost, and safety margin.
  * **Premium**: The design with the lowest Cumulative Damage Factor, yielding maximum pavement life.

---

## 🖥️ How to Use the Web Application

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
* **Reliability Level**: Select the target design reliability (e.g., 90% or 95%).
* **Axle Configuration**: Define wheel loads, contact pressure, and coordinates for structural strain analysis.

### Step 3: Run the Optimizer
1. Under **Opt Target**, toggle whether to optimize by **Thickness**, **Cost**, or **Carbon Footprint (CO₂)**.
2. Click **Run Optimizer**.
3. The comparison charts and three archetype design cards (Economy, Balanced, Premium) will populate instantly. Click on any archetype card to inspect its detailed layer layout and strain margins.

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
