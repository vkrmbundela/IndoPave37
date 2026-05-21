# FlexPave Engineering Cockpit & Solver Suite

FlexPave is a high-performance pavement analysis, structural evaluation, and optimization platform aligned with **IRC:37-2019** (for highway design) and **IRC:SP:72-2015** (for low-volume roads). It wraps the legacy **IIT Pave Fortran executable** in a thread-safe Python bridge and offers an interactive, premium **Zero-Scroll CAD-like dashboard** built with React and Tailwind CSS v4.

---

## 🚀 One-Click Quick Start (Windows)

To start both the frontend and backend servers locally with a single click, run:
```bash
.\run_local.bat
```
This batch script will:
1. Automatically search for a Python virtual environment (`.venv` or `venv`).
2. Install Python dependencies from `mep_opt/requirements.txt` if needed.
3. Check if frontend node packages are present (and run `npm install` if missing).
4. Spin up the FastAPI backend on `http://127.0.0.1:8000`.
5. Launch the Vite dev server and automatically open the dashboard in your default browser.

---

## 🛠️ Architecture & Tech Stack

```
                                  +------------------------------------+
                                  |         React 19 Frontend          |
                                  |       (Hosted on GitHub Pages)     |
                                  +-----------------+------------------+
                                                    |
                                           REST API / JSON
                                                    |
                                                    v
                                  +------------------------------------+
                                  |          FastAPI Backend           |
                                  |     (Runs Locally / Uvicorn)       |
                                  +-----------------+------------------+
                                                    |
                                            Temp File Bridge
                                                    |
                                                    v
                                  +------------------------------------+
                                  |     IIT Pave Legacy Executable     |
                                  |    (Fortran Solver, Thread-Safe)   |
                                  +------------------------------------+
```

* **Frontend**: React 19, Vite, Tailwind CSS v4, and Recharts. Hosted statically on GitHub Pages.
* **Backend**: Python 3.10+ (FastAPI, Uvicorn) wrapping the legacy Fortran bridge (`iitpave_bridge.py`). Runs locally on your machine.
* **Database/Solver**: Local database of materials properties and automated design equation compliance against **IRC:37-2019** and **IRC:SP:72-2015**.

---

## 🎯 Key Features

1. **Smart Search Optimizer**: A deterministic two-phase search engine (Cheapest-first Greedy Climb followed by a Boundary Grid Sweep) that compiles three design archetypes:
   - **Economy**: Thinnest adequate design.
   - **Balanced**: Best trade-off in thickness, cost, and safety margin.
   - **Premium**: Lowest Cumulative Damage Factor (CDF) for maximum pavement life.
2. **Advanced Panels**:
   - **3D Strain Bulbs**: Interactive visualization of strain fields under standard dual-wheel axle loads.
   - **Monte Carlo Sensitivity**: Run stochastic evaluations on material properties and layer thicknesses to see reliability profiles.
   - **Low-Volume Roads (IRC:SP:72-2015)**: Multi-regime design calculations for low-traffic rural pavement layers.
   - **Geosynthetic Layer Reinforcement**: Design and evaluate subgrades reinforced with geosynthetic materials.
3. **Persisted Design System**: Custom layout splitter preserving panels with automated local storage caching and JSON configuration export/import.

---

## 🔬 Solver Accuracy & Validation

FlexPave has been validated against classical benchmark cases (**rps1**, **case2**, and **TIHAN1**):
* **Accuracy**: Computes critical tensile strain ($\varepsilon_t$) and vertical subgrade strain ($\varepsilon_v$) within **<1–2%** deviation from the legacy Fortran outputs.
* **Test Suite**: Includes 190+ automated tests verifying optimization limits, material modulus calculations, and IRC compliance.

---

## 🔧 Manual Setup & Commands

If you prefer to run servers individually:

### 1. Backend Setup & Startup
```bash
# Initialize virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install requirements
pip install -r mep_opt/requirements.txt

# Start FastAPI server
python -m mep_opt.web.main
```
The backend server runs on `http://127.0.0.1:8000`.

### 2. Frontend Setup & Startup
```bash
cd frontend
npm install
npm run dev
```
The frontend dev server runs on `http://localhost:5173`.

### 3. Run Backend Tests
```bash
.\.venv\Scripts\pytest mep_opt/tests/ -v
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
