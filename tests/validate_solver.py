"""
Solver Validation Harness
=========================
Compares the pure-Python Burmister solver against the legacy bridge (.EXE)
on a set of benchmark cases covering realistic IRC:37 pavement sections.

Run:
    python tests/validate_solver.py

Output:
    Per-case comparison of eps_z, eps_t, sigma_z, sigma_t, disp_z
    with absolute and percentage errors. Summary pass/fail at the end.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mep_opt.solver.burmister import analyze_pavement
from mep_opt.solver.iitpave_bridge import is_iitpave_available, run_iitpave_bridge


BENCHMARK_CASES = [
    {
        "name": "3-layer: BC(50) / GSB(250) / Subgrade",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 50},
            {"modulus": 200,  "poisson": 0.35, "thickness": 250},
            {"modulus": 50,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [
            {"z": 50,  "r": 0},
            {"z": 300, "r": 0},
        ],
    },
    {
        "name": "4-layer: BC(40) / DBM(60) / WMM(250) / Subgrade",
        "stack": [
            {"modulus": 3000, "poisson": 0.35, "thickness": 40},
            {"modulus": 2000, "poisson": 0.35, "thickness": 60},
            {"modulus": 300,  "poisson": 0.35, "thickness": 250},
            {"modulus": 62,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [
            {"z": 40,  "r": 0},
            {"z": 100, "r": 0},
            {"z": 350, "r": 0},
        ],
    },
    {
        "name": "4-layer: BC(50) / DBM(100) / Granular(300) / Subgrade",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 50},
            {"modulus": 2000, "poisson": 0.35, "thickness": 100},
            {"modulus": 209,  "poisson": 0.35, "thickness": 300},
            {"modulus": 80,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [
            {"z": 50,  "r": 0},
            {"z": 150, "r": 0},
            {"z": 450, "r": 0},
        ],
    },
    {
        "name": "5-layer: SMA(40)/BC(60)/DBM(80)/WMM(250)/Subgrade",
        "stack": [
            {"modulus": 1600, "poisson": 0.35, "thickness": 40},
            {"modulus": 3000, "poisson": 0.35, "thickness": 60},
            {"modulus": 2000, "poisson": 0.35, "thickness": 80},
            {"modulus": 250,  "poisson": 0.35, "thickness": 250},
            {"modulus": 50,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [
            {"z": 40,  "r": 0},
            {"z": 100, "r": 0},
            {"z": 180, "r": 0},
            {"z": 430, "r": 0},
        ],
    },
    {
        "name": "Single wheel: BC(75) / GSB(200) / Subgrade",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 75},
            {"modulus": 200,  "poisson": 0.35, "thickness": 200},
            {"modulus": 50,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 40000, "pressure": 0.56, "is_dual": False, "spacing": 310},
        "points": [
            {"z": 75,  "r": 0},
            {"z": 275, "r": 0},
        ],
    },
    {
        "name": "Off-axis eval: BC(50) / DBM(100) / Gran(250) / Subgrade",
        "stack": [
            {"modulus": 2000, "poisson": 0.35, "thickness": 50},
            {"modulus": 2000, "poisson": 0.35, "thickness": 100},
            {"modulus": 209,  "poisson": 0.35, "thickness": 250},
            {"modulus": 80,   "poisson": 0.40, "thickness": 0},
        ],
        "load": {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
        "points": [
            {"z": 150, "r": 155},
            {"z": 400, "r": 155},
        ],
    },
]

COMPARE_KEYS = ["eps_z", "eps_t", "eps_r", "sigma_z", "sigma_t", "disp_z"]
TOLERANCE_PCT = 1.0  # maximum acceptable % error


def _pct_err(native_val, bridge_val):
    if abs(bridge_val) < 1e-15:
        return 0.0 if abs(native_val) < 1e-15 else float("inf")
    return abs(native_val - bridge_val) / abs(bridge_val) * 100.0


def _fmt(val):
    return f"{val:+.6e}"


def run_validation():
    if not is_iitpave_available():
        print("ERROR: Legacy bridge (.EXE) not available — cannot validate.")
        print("       The bridge is needed as the reference truth.")
        sys.exit(1)

    print("=" * 78)
    print("  BURMISTER SOLVER VALIDATION — Native Python vs Legacy Bridge (.EXE)")
    print("=" * 78)
    print()

    total_comparisons = 0
    total_pass = 0
    total_fail = 0
    max_err_seen = 0.0
    worst_case = ""
    case_results = []

    for case in BENCHMARK_CASES:
        name = case["name"]
        stack = case["stack"]
        load = case["load"]
        points = case["points"]

        print(f"--- {name} ---")

        # Run bridge (reference truth)
        t0 = time.perf_counter()
        try:
            bridge_res = run_iitpave_bridge(stack, load, points)
        except Exception as e:
            print(f"  BRIDGE ERROR: {e}")
            print()
            continue
        t_bridge = (time.perf_counter() - t0) * 1000

        # Run native Python solver
        t0 = time.perf_counter()
        try:
            native_res = analyze_pavement(stack, load, points)
        except Exception as e:
            print(f"  NATIVE ERROR: {e}")
            print()
            case_results.append({"name": name, "status": "NATIVE_ERROR", "error": str(e)})
            continue
        t_native = (time.perf_counter() - t0) * 1000

        print(f"  Timing: Bridge={t_bridge:.1f}ms  Native={t_native:.1f}ms  "
              f"Speedup={t_bridge/max(t_native,0.01):.1f}x")

        case_pass = True
        case_max_err = 0.0

        for pi, (nr, br) in enumerate(zip(native_res, bridge_res)):
            z, r = br["z"], br["r"]
            print(f"  Point (z={z}, r={r}):")

            for key in COMPARE_KEYS:
                nv = nr.get(key, 0.0)
                bv = br.get(key, 0.0)
                err = _pct_err(nv, bv)
                ok = err <= TOLERANCE_PCT
                status = "OK" if ok else "FAIL"

                total_comparisons += 1
                if ok:
                    total_pass += 1
                else:
                    total_fail += 1
                    case_pass = False

                if err > max_err_seen:
                    max_err_seen = err
                    worst_case = f"{name} / z={z},r={r} / {key}"
                if err > case_max_err:
                    case_max_err = err

                print(f"    {key:>10s}:  native={_fmt(nv)}  bridge={_fmt(bv)}  "
                      f"err={err:6.2f}%  [{status}]")

        status_str = "PASS" if case_pass else "FAIL"
        print(f"  Case result: {status_str}  (max err: {case_max_err:.2f}%)")
        print()
        case_results.append({
            "name": name, "status": status_str, "max_err": case_max_err,
            "t_bridge_ms": t_bridge, "t_native_ms": t_native,
        })

    # Summary
    print("=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    print(f"  Cases run:          {len(case_results)}")
    print(f"  Total comparisons:  {total_comparisons}")
    print(f"  Passed:             {total_pass}")
    print(f"  Failed:             {total_fail}")
    print(f"  Max error seen:     {max_err_seen:.4f}%")
    if worst_case:
        print(f"  Worst case:         {worst_case}")
    print(f"  Tolerance:          {TOLERANCE_PCT}%")
    print()

    all_passed = total_fail == 0
    if all_passed:
        print("  >>> ALL CHECKS PASSED — Native solver matches bridge within tolerance <<<")
    else:
        print("  >>> SOME CHECKS FAILED — Native solver needs calibration <<<")
    print()

    # Per-case table
    print("  Case Results:")
    for cr in case_results:
        if "max_err" in cr:
            print(f"    [{cr['status']:4s}] {cr['name']:<55s}  "
                  f"err={cr['max_err']:.2f}%  "
                  f"bridge={cr['t_bridge_ms']:.0f}ms  "
                  f"native={cr['t_native_ms']:.0f}ms")
        else:
            print(f"    [{cr['status']}] {cr['name']}")

    print()
    return all_passed


if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)
