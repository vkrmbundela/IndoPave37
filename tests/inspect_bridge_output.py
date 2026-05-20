"""
Diagnostic: run the bridge on a test case and dump the raw OUT file
alongside the parsed results to verify the parser is correct.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mep_opt.solver.iitpave_bridge import (
    run_iitpave_bridge, LEGACY_OUT_FILE, LEGACY_DIR, LEGACY_EXE
)

CASES = [
    {
        "name": "DUAL WHEEL",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 50},
            {"modulus": 200,  "poisson": 0.35, "thickness": 250},
            {"modulus": 50,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [{"z": 50, "r": 0}, {"z": 300, "r": 0}],
    },
    {
        "name": "SINGLE WHEEL",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 75},
            {"modulus": 200,  "poisson": 0.35, "thickness": 200},
            {"modulus": 50,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 40000, "pressure": 0.56, "is_dual": False, "spacing": 310},
        "points": [{"z": 75, "r": 0}, {"z": 275, "r": 0}],
    },
]

print(f"EXE: {LEGACY_EXE}")
print(f"DIR: {LEGACY_DIR}")
print()

for CASE in CASES:
    print(f"\n{'='*60}")
    print(f"  {CASE['name']}")
    print(f"{'='*60}")

    result = run_iitpave_bridge(CASE["stack"], CASE["load"], CASE["points"])

    print("\n=== RAW OUT FILE ===")
    with open(LEGACY_OUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    print(raw)

    print("=== PARSED RESULTS ===")
    for i, r in enumerate(result):
        print(f"  Point {i}: z={r['z']}, r={r['r']}")
        print(f"    sigma_z={r['sigma_z']:.6e}  sigma_t={r['sigma_t']:.6e}  sigma_r={r['sigma_r']:.6e}")
        print(f"    eps_z={r['eps_z']:.6e}  eps_t={r['eps_t']:.6e}  eps_r={r['eps_r']:.6e}")
        print(f"    disp_z={r['disp_z']:.6e}")

    print("\n=== DATA LINES (with L-row detection) ===")
    lines = raw.splitlines()
    float_re = r"[+-]?(?:\d*\.\d+|\d+)(?:[EeDd][+-]?\d+)?"
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        nums = re.findall(float_re, stripped)
        is_L = 'L' in stripped.split()[0] if stripped.split() else False
        if len(nums) >= 6:
            tag = " [L-ROW]" if is_L else ""
            print(f"  Line {i:2d}{tag}: z={nums[0]:>8s}  epZ={nums[-3]:>14s}  epT={nums[-2]:>14s}  sigZ={nums[2]:>14s}  sigT={nums[3]:>14s}")
