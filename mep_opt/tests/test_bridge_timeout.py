"""
Tests for the IIT Pave bridge timeout behavior (Issue #20).

The legacy executable typically returns in under 1 second, so a hard
hang is rare — but the timeout protection must work when it does.
We test the public-API surface (parameter wiring, exception types)
without actually hanging the executable.
"""

import inspect
import math

import pytest

from mep_opt.solver import iitpave_bridge
from mep_opt.solver.legacy_bridge import (
    BridgeTimeoutError,
    DEFAULT_BRIDGE_TIMEOUT_S,
    run_bridge_from_stack,
    run_legacy_bridge,
)


def test_default_timeout_is_a_finite_positive_number():
    """The shipped default must be reasonable for production use."""
    assert isinstance(DEFAULT_BRIDGE_TIMEOUT_S, (int, float))
    assert 1.0 <= DEFAULT_BRIDGE_TIMEOUT_S <= 300.0, (
        f"Default bridge timeout {DEFAULT_BRIDGE_TIMEOUT_S}s is outside "
        f"the engineering-reasonable 1–300 s window"
    )


def test_bridge_timeout_error_is_a_runtime_error():
    """Callers should be able to except RuntimeError and catch this too."""
    assert issubclass(BridgeTimeoutError, RuntimeError)


def test_run_bridge_from_stack_accepts_timeout_kwarg():
    """All public bridge entry points must expose a `timeout=` parameter."""
    sig = inspect.signature(run_bridge_from_stack)
    assert "timeout" in sig.parameters
    assert sig.parameters["timeout"].default == DEFAULT_BRIDGE_TIMEOUT_S


def test_run_legacy_bridge_accepts_timeout_kwarg():
    sig = inspect.signature(run_legacy_bridge)
    assert "timeout" in sig.parameters
    assert sig.parameters["timeout"].default == DEFAULT_BRIDGE_TIMEOUT_S


def test_run_iitpave_bridge_accepts_timeout_kwarg():
    sig = inspect.signature(iitpave_bridge.run_iitpave_bridge)
    assert "timeout" in sig.parameters
    assert sig.parameters["timeout"].default == DEFAULT_BRIDGE_TIMEOUT_S


def test_subprocess_timeout_path_translates_to_bridge_timeout_error(monkeypatch):
    """
    A subprocess.TimeoutExpired must be wrapped as BridgeTimeoutError so
    callers can distinguish a hung executable from a CalledProcessError
    (non-zero exit) or a parse failure.
    """
    import subprocess

    # Force the executable-existence check to pass without touching disk.
    monkeypatch.setattr(iitpave_bridge.os.path, "exists", lambda _p: True)

    # Skip writing the IN file (that path touches disk).
    monkeypatch.setattr(iitpave_bridge, "_write_in_file", lambda *a, **kw: None)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(iitpave_bridge.subprocess, "run", fake_run)

    with pytest.raises(BridgeTimeoutError, match="exceeded"):
        iitpave_bridge.run_iitpave_bridge(
            solver_stack=[
                {"modulus": 1250.0, "poisson": 0.35, "thickness": 40},
                {"modulus": 200.0,  "poisson": 0.40, "thickness": 0},
            ],
            load_cfg={"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310},
            eval_points=[{"z": 39.9, "r": 0}],
            timeout=0.001,
        )


def test_parse_out_file_handles_merged_numbers_and_d_exponents():
    """Legacy OUT rows with tight spacing and D exponents should still parse."""
    lines = [
        "     Z        R      SigmaZ      SigmaT     SigmaR     TaoRZ      DispZ      epZ        epT        epR",
        "    55.00    0.00-0.4108D+00 0.6959D+00 0.6087D+00-0.1910D-01 0.4357D+00-0.2478D-03 0.1790D-03 0.1454D-03 0.1454D-03",
    ]

    parsed = iitpave_bridge._parse_out_file(lines, [{"z": 55.0, "r": 0.0}])

    assert len(parsed) == 1
    assert parsed[0]["z"] == 55.0
    assert parsed[0]["r"] == 0.0
    assert parsed[0]["eps_z"] == pytest.approx(0.1790e-03)
    assert parsed[0]["eps_t"] == pytest.approx(0.1454e-03)
    assert math.isfinite(parsed[0]["sigma_z"])
    assert math.isfinite(parsed[0]["sigma_t"])
