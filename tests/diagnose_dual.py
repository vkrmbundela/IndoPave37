"""
Diagnostic: isolate whether dual-wheel errors come from
single-wheel evaluation at r>0 or from the superposition logic.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mep_opt.solver.burmister import BurmisterSolver, LayerProperty, LoadConfig, EvalPoint
from mep_opt.solver.iitpave_bridge import run_iitpave_bridge

# 3-layer structure: BC(50) / GSB(250) / Subgrade
STACK = [
    {"modulus": 2000, "poisson": 0.35, "thickness": 50},
    {"modulus": 200,  "poisson": 0.35, "thickness": 250},
    {"modulus": 50,   "poisson": 0.40, "thickness": 0},
]

# Test 1: Single wheel via bridge at r=0 and r=155
print("=== TEST 1: Single wheel via bridge at r=0 and r=155 ===")
load_single = {"load": 20000, "pressure": 0.56, "is_dual": False, "spacing": 310}
pts = [{"z": 50, "r": 0}, {"z": 50, "r": 155}]
bridge_single = run_iitpave_bridge(STACK, load_single, pts)
for i, r in enumerate(bridge_single):
    print(f"  Bridge single z=50,r={pts[i]['r']:>3}: sig_z={r['sigma_z']:+.4e}  sig_t={r['sigma_t']:+.4e}  sig_r={r['sigma_r']:+.4e}  eps_z={r['eps_z']:+.4e}  eps_t={r['eps_t']:+.4e}  disp_z={r['disp_z']:+.4e}")

# Test 2: Native single wheel at same points
print("\n=== TEST 2: Native single wheel at r=0 and r=155 ===")
layers = [LayerProperty(s["modulus"], s["poisson"], s["thickness"]) for s in STACK]
load_obj = LoadConfig(load=20000, pressure=0.56, is_dual=False, spacing=310)
solver = BurmisterSolver(layers, load_obj)
pts_obj = [EvalPoint(50, 0), EvalPoint(50, 155)]
native_single = solver.solve(pts_obj)
for i, r in enumerate(native_single):
    print(f"  Native single z=50,r={pts_obj[i].r:>3}: sig_z={r.sigma_z:+.4e}  sig_t={r.sigma_t:+.4e}  sig_r={r.sigma_r:+.4e}  eps_z={r.eps_z:+.4e}  eps_t={r.eps_t:+.4e}  disp_z={r.disp_z:+.4e}")

# Compare single wheel at r=155
b = bridge_single[1]
n = native_single[1]
print("\n=== SINGLE WHEEL r=155 COMPARISON ===")
for key in ["sigma_z", "sigma_t", "sigma_r", "eps_z", "eps_t", "disp_z"]:
    bv = getattr(b, key, None) or b[key]
    nv = getattr(n, key, None) if hasattr(n, key) else n.__dict__[key]
    err = abs(nv - bv) / abs(bv) * 100 if abs(bv) > 1e-15 else 0
    print(f"  {key:>10s}: native={nv:+.6e}  bridge={bv:+.6e}  err={err:.2f}%")

# Test 3: Dual wheel via bridge
print("\n=== TEST 3: Dual wheel via bridge ===")
load_dual = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
pts_dual = [{"z": 50, "r": 0}]
bridge_dual = run_iitpave_bridge(STACK, load_dual, pts_dual)
r = bridge_dual[0]
print(f"  Bridge dual  z=50,r=0: sig_z={r['sigma_z']:+.4e}  sig_t={r['sigma_t']:+.4e}  sig_r={r['sigma_r']:+.4e}  eps_z={r['eps_z']:+.4e}  eps_t={r['eps_t']:+.4e}  disp_z={r['disp_z']:+.4e}")

# Test 4: Manual dual superposition from bridge single-wheel at r=155
s1 = bridge_single[1]  # single wheel at r=155
print(f"\n=== TEST 4: Manual dual from 2x bridge single@r=155 ===")
print(f"  2x single  z=50,r=0: sig_z={2*s1['sigma_z']:+.4e}  sig_t={2*s1['sigma_t']:+.4e}  sig_r={2*s1['sigma_r']:+.4e}  eps_z=N/A  eps_t={2*s1['eps_t']:+.4e}  disp_z={2*s1['disp_z']:+.4e}")

# Test 5: Native dual wheel
print("\n=== TEST 5: Native dual wheel ===")
load_dual_obj = LoadConfig(load=20000, pressure=0.56, is_dual=True, spacing=310)
solver_dual = BurmisterSolver(layers, load_dual_obj)
native_dual = solver_dual.solve([EvalPoint(50, 0)])
n = native_dual[0]
print(f"  Native dual z=50,r=0: sig_z={n.sigma_z:+.4e}  sig_t={n.sigma_t:+.4e}  sig_r={n.sigma_r:+.4e}  eps_z={n.eps_z:+.4e}  eps_t={n.eps_t:+.4e}  disp_z={n.disp_z:+.4e}")
