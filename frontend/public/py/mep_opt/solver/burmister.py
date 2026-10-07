"""
Burmister Multi-Layer Elastic Analysis Solver
==============================================
Computes stresses, strains, and displacements in a layered elastic
pavement system under uniform circular loading.

Method:
  Direct coefficient method using the general axisymmetric solution
  derived from the Navier equations in cylindrical coordinates.
  For each Hankel parameter m, we set up continuity/boundary conditions
  on the 4 coefficients per finite layer (+ 2 for half-space) and
  solve the resulting linear system.
  Gauss-Legendre quadrature for Hankel transform inversion.

General Solution (verified by direct substitution into Navier equations):
  DECAYING part (e^{-mz}):
    uz_dec = [A + D(kap + mz)] e^{-mz}
    ur_dec = [A + D*mz] e^{-mz}
  GROWING part (e^{+mz}):
    uz_grow = [C + B(kap - mz)] e^{+mz}
    ur_grow = [-C + B*mz] e^{+mz}

Stress formulas (Hankel domain):
  sigz = (lam+2G) duz/dz + lam*m*ur    (PLUS sign!)
  tau  = G * (dur/dz - m*uz)

Reference:
  Huang Y.H. (1993) "Pavement Analysis and Design"
  IRC:37-2018 (IITPAVE algorithm)
"""

import numpy as np
from scipy.special import j0 as bessel_j0, j1 as bessel_j1, ellipe, ellipk
from dataclasses import dataclass, replace
from typing import List

# ---------------------------------------------------------------------------
# Near-surface quadrature controls
# ---------------------------------------------------------------------------
# The Hankel integrands decay like exp(-m*z). The fixed IITPAVE-style interval
# scheme (cut-off m = 60/a) is converged only once z is a sizeable fraction of
# the contact radius a; closer to the surface it truncates and aliases the
# slowly-decaying integrand (sigma_z was +140% at z = 1 mm, surface deflection
# +3%). Shallow points therefore use (a) subtraction of the top layer's
# half-space kernel, whose integral is evaluated exactly, and (b) refined
# panels extended until exp(-m*z_decay) is negligible.
_NEAR_SURFACE_FACTOR = 0.75   # z_decay < 0.75*a -> refined treatment
_DECAY_TARGET = 40.0          # integrate until m*z_decay >= 40 (e^-40 ~ 4e-18)
_REFINED_PANEL = 2.0          # refined panel width = 2 / max(a, r)  [1/mm]
SURFACE_Z_TOL = 0.5           # mm: shallower points are evaluated at z = 0
# The fixed IITPAVE intervals (GL4 panels up to 20/a wide) alias the J0/J1
# oscillation once r is several contact radii; such far-field points use the
# refined panels at every depth. All IRC design points (r <= 310 mm under the
# standard and CTB loads) stay on the IITPAVE intervals.
_FAR_FIELD_FACTOR = 4.0
# Upper bound on refined panels for one integral (8 nodes each). Reached only
# for extreme inputs (sub-millimetre top layers far from the load); the panels
# are then widened uniformly instead of letting the cost grow without bound.
_MAX_REFINED_PANELS = 50000
_MAX_PANEL_WIDENING = 8       # beyond this the result would be unreliable: refuse
_KERNEL_CHUNK = 2048          # Hankel nodes per batched linear solve
MIN_LAYER_THICKNESS = 1.0     # mm; thinner finite layers are not modelled (0 = omit)
MAX_RADIAL_OFFSET = 20000.0   # mm; evaluation points farther from the load are refused
# Interface bond is modelled as either fully bonded or frictionless; partial
# bond (e.g. Goodman interface springs) is not implemented, so intermediate
# friction factors are rejected rather than silently rounded.
_BONDED_MIN = 0.999
_UNBONDED_MAX = 1e-9

_GL8_N, _GL8_W = np.polynomial.legendre.leggauss(8)


# ---------------------------------------------------------------------------
# Gauss-Legendre quadrature (from IITPAVE gauss.qua, symmetric completion)
# ---------------------------------------------------------------------------

_GL10_HN = np.array([
    -0.973906528517172, -0.865063366688985, -0.679409568299024,
    -0.433395394129247, -0.148874338981631,
])
_GL10_HW = np.array([
    0.066671344308688, 0.149451349150581, 0.219086362515982,
    0.269266719309996, 0.295524224714753,
])
GL10_N = np.concatenate([_GL10_HN, -_GL10_HN[::-1]])
GL10_W = np.concatenate([_GL10_HW, _GL10_HW[::-1]])

_GL6_HN = np.array([-0.932469514203152, -0.661209386466265, -0.238619186083197])
_GL6_HW = np.array([0.171324492379170, 0.360761573048139, 0.467913934572691])
GL6_N = np.concatenate([_GL6_HN, -_GL6_HN[::-1]])
GL6_W = np.concatenate([_GL6_HW, _GL6_HW[::-1]])

_GL4_HN = np.array([-0.861136311594053, -0.339981043584856])
_GL4_HW = np.array([0.347854845137454, 0.652145154862546])
GL4_N = np.concatenate([_GL4_HN, -_GL4_HN[::-1]])
GL4_W = np.concatenate([_GL4_HW, _GL4_HW[::-1]])


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LayerProperty:
    modulus: float      # E in MPa
    poisson: float      # nu (dimensionless)
    thickness: float    # h in mm (0 for half-space)
    friction_factor: float = 1.0  # 1.0 = fully bonded, 0.0 = completely unbonded


@dataclass
class LoadConfig:
    load: float         # P in Newtons
    pressure: float     # q in MPa
    is_dual: bool = False
    spacing: float = 310.0  # mm, center-to-center for dual wheel

    @property
    def radius(self) -> float:
        """Contact radius a = sqrt(P / (pi * q))"""
        return np.sqrt(self.load / (np.pi * self.pressure))

@dataclass
class EvalPoint:
    z: float    # depth in mm
    r: float    # radial distance in mm

@dataclass
class ResponseResult:
    z: float
    r: float
    sigma_z: float
    sigma_r: float
    sigma_t: float
    tau_rz: float
    disp_z: float
    disp_r: float
    eps_z: float
    eps_r: float
    eps_t: float


# ---------------------------------------------------------------------------
# General axisymmetric solution in Hankel domain (CORRECTED)
# ---------------------------------------------------------------------------
#
# Full solution for a finite layer (4 free parameters: A, D, C, B):
#   uz = [A + D(kap+mz)]e^{-mz} + [C + B(kap-mz)]e^{+mz}
#   ur = [A + D*mz]e^{-mz} + [-C + B*mz]e^{+mz}
#
# Derivatives:
#   duz/dz = -m[A + D(kap-1+mz)]e^{-mz} + m[C + B(kap-1-mz)]e^{+mz}
#   dur/dz = -m[A - D + D*mz]e^{-mz} + m[-C + B(1+mz)]e^{+mz}
#
# For numerical stability, scale the growing part:
#   C' = C*exp(mh), B' = B*exp(mh)
#   Then: C*e^{+mz} = C'*e^{-m(h-z)}, B*e^{+mz} = B'*e^{-m(h-z)}
#   So all exponentials are of decaying type (argument <= 0).
#
# Coefficient ordering: [A, D, C', B'] for each finite layer
#                        [A, D] for the half-space (C=B=0)
#
# Stresses (CORRECT signs from Hankel transform identities):
#   sigz = (lam+2G) duz/dz + lam*m*ur
#   tau  = G*(dur/dz - m*uz)
# ---------------------------------------------------------------------------


def _safe_exp(x):
    """Exponential with underflow protection."""
    return np.exp(x) if x > -500 else 0.0


def _finite_state_matrix(m, z_loc, h, E_i, nu_i):
    """
    4x4 matrix M such that [uz, ur, sigz, tau] = M @ [A, D, C', B']
    at local depth z_loc within a finite layer of thickness h.
    Uses only decaying exponentials for numerical stability.
    """
    G_i = E_i / (2.0 * (1.0 + nu_i))
    lam_i = 2.0 * G_i * nu_i / (1.0 - 2.0 * nu_i)
    kap = 3.0 - 4.0 * nu_i
    L2G = lam_i + 2.0 * G_i

    mz = m * z_loc
    mhz = m * (h - z_loc)
    emz = _safe_exp(-mz)
    emhz = _safe_exp(-mhz)

    M = np.zeros((4, 4))

    # --- uz ---
    # uz = [A + D(kap+mz)]emz + [C' + B'(kap-mz)]emhz
    M[0, 0] = emz                       # A
    M[0, 1] = (kap + mz) * emz          # D
    M[0, 2] = emhz                      # C'
    M[0, 3] = (kap - mz) * emhz         # B'

    # --- ur ---
    # ur = [A + D*mz]emz + [-C' + B'*mz]emhz
    M[1, 0] = emz                       # A
    M[1, 1] = mz * emz                  # D
    M[1, 2] = -emhz                     # C'
    M[1, 3] = mz * emhz                 # B'

    # --- duz/dz ---
    # duz/dz = -m[A + D(kap-1+mz)]emz + m[C' + B'(kap-1-mz)]emhz
    duz_A = -m * emz
    duz_D = -m * (kap - 1 + mz) * emz
    duz_Cp = m * emhz
    duz_Bp = m * (kap - 1 - mz) * emhz

    # --- dur/dz ---
    # dur/dz = -m[A - D + D*mz]emz + m[-C' + B'(1+mz)]emhz
    dur_A = -m * emz
    dur_D = m * (1 - mz) * emz           # = -m(-1+mz)*emz = m*(1-mz)*emz
    dur_Cp = -m * emhz
    dur_Bp = m * (1 + mz) * emhz

    # --- sigz = L2G * duz/dz + lam * m * ur ---
    M[2, 0] = L2G * duz_A + lam_i * m * M[1, 0]
    M[2, 1] = L2G * duz_D + lam_i * m * M[1, 1]
    M[2, 2] = L2G * duz_Cp + lam_i * m * M[1, 2]
    M[2, 3] = L2G * duz_Bp + lam_i * m * M[1, 3]

    # --- tau = G * (dur/dz - m * uz) ---
    M[3, 0] = G_i * (dur_A - m * M[0, 0])
    M[3, 1] = G_i * (dur_D - m * M[0, 1])
    M[3, 2] = G_i * (dur_Cp - m * M[0, 2])
    M[3, 3] = G_i * (dur_Bp - m * M[0, 3])

    return M


def _halfspace_state_matrix(m, z_loc, E_n, nu_n):
    """
    4x2 matrix M such that [uz, ur, sigz, tau] = M @ [A, D]
    at local depth z_loc within the half-space (C=B=0, decaying only).
    """
    G_n = E_n / (2.0 * (1.0 + nu_n))
    lam_n = 2.0 * G_n * nu_n / (1.0 - 2.0 * nu_n)
    kap = 3.0 - 4.0 * nu_n
    L2G = lam_n + 2.0 * G_n

    mz = m * z_loc
    emz = _safe_exp(-mz)

    M = np.zeros((4, 2))

    # uz = [A + D(kap+mz)] emz
    M[0, 0] = emz
    M[0, 1] = (kap + mz) * emz

    # ur = [A + D*mz] emz
    M[1, 0] = emz
    M[1, 1] = mz * emz

    # duz/dz = -m[A + D(kap-1+mz)] emz
    duz_A = -m * emz
    duz_D = -m * (kap - 1 + mz) * emz

    # dur/dz = -m[A - D + D*mz] emz
    dur_A = -m * emz
    dur_D = m * (1 - mz) * emz

    # sigz = L2G * duz/dz + lam * m * ur
    M[2, 0] = L2G * duz_A + lam_n * m * M[1, 0]
    M[2, 1] = L2G * duz_D + lam_n * m * M[1, 1]

    # tau = G * (dur/dz - m * uz)
    M[3, 0] = G_n * (dur_A - m * M[0, 0])
    M[3, 1] = G_n * (dur_D - m * M[0, 1])

    return M


def _eval_state_finite(m, z_loc, h, E_i, nu_i, coeffs):
    """
    Evaluate [uz, ur, sigz, tau] at local depth z_loc within a finite layer.
    coeffs = [A, D, C', B'].
    """
    M = _finite_state_matrix(m, z_loc, h, E_i, nu_i)
    return M @ coeffs


def _eval_state_halfspace(m, z_loc, E_n, nu_n, coeffs):
    """
    Evaluate [uz, ur, sigz, tau] at local depth z_loc within the half-space.
    coeffs = [A, D].
    """
    M = _halfspace_state_matrix(m, z_loc, E_n, nu_n)
    return M @ coeffs


# Vectorised (over an array of Hankel parameters m) copies of the two state
# matrices above, element for element the same arithmetic, so a batch of
# linear systems can be assembled and solved in one call.

def _safe_exp_vec(x):
    x = np.asarray(x, dtype=float)
    return np.where(x > -500.0, np.exp(np.maximum(x, -500.0)), 0.0)


def _finite_state_matrix_vec(m, z_loc, h, E_i, nu_i):
    """(K, 4, 4) stack of _finite_state_matrix for the array m (shape (K,))."""
    G_i = E_i / (2.0 * (1.0 + nu_i))
    lam_i = 2.0 * G_i * nu_i / (1.0 - 2.0 * nu_i)
    kap = 3.0 - 4.0 * nu_i
    L2G = lam_i + 2.0 * G_i

    mz = m * z_loc
    mhz = m * (h - z_loc)
    emz = _safe_exp_vec(-mz)
    emhz = _safe_exp_vec(-mhz)

    M = np.zeros(m.shape + (4, 4))
    M[:, 0, 0] = emz
    M[:, 0, 1] = (kap + mz) * emz
    M[:, 0, 2] = emhz
    M[:, 0, 3] = (kap - mz) * emhz
    M[:, 1, 0] = emz
    M[:, 1, 1] = mz * emz
    M[:, 1, 2] = -emhz
    M[:, 1, 3] = mz * emhz

    duz = (-m * emz, -m * (kap - 1 + mz) * emz, m * emhz, m * (kap - 1 - mz) * emhz)
    dur = (-m * emz, m * (1 - mz) * emz, -m * emhz, m * (1 + mz) * emhz)
    for j in range(4):
        M[:, 2, j] = L2G * duz[j] + lam_i * m * M[:, 1, j]
        M[:, 3, j] = G_i * (dur[j] - m * M[:, 0, j])
    return M


def _halfspace_state_matrix_vec(m, z_loc, E_n, nu_n):
    """(K, 4, 2) stack of _halfspace_state_matrix for the array m."""
    G_n = E_n / (2.0 * (1.0 + nu_n))
    lam_n = 2.0 * G_n * nu_n / (1.0 - 2.0 * nu_n)
    kap = 3.0 - 4.0 * nu_n
    L2G = lam_n + 2.0 * G_n

    mz = m * z_loc
    emz = _safe_exp_vec(-mz)

    M = np.zeros(m.shape + (4, 2))
    M[:, 0, 0] = emz
    M[:, 0, 1] = (kap + mz) * emz
    M[:, 1, 0] = emz
    M[:, 1, 1] = mz * emz

    duz = (-m * emz, -m * (kap - 1 + mz) * emz)
    dur = (-m * emz, m * (1 - mz) * emz)
    for j in range(2):
        M[:, 2, j] = L2G * duz[j] + lam_n * m * M[:, 1, j]
        M[:, 3, j] = G_n * (dur[j] - m * M[:, 0, j])
    return M


def _validate_points(points) -> None:
    """Evaluation points must be finite with z >= 0 (r is a radius; its sign is ignored)."""
    for k, p in enumerate(points):
        z, r = p.z, p.r
        if not np.isfinite(z) or z < 0:
            raise ValueError(f"Evaluation point {k + 1}: depth z must be finite and >= 0 mm (got {z!r})")
        if not np.isfinite(r) or abs(r) > MAX_RADIAL_OFFSET:
            raise ValueError(f"Evaluation point {k + 1}: radial offset r must be finite and within "
                             f"{MAX_RADIAL_OFFSET:.0f} mm of the load (got {r!r})")


def _validate_inputs(layers: List[LayerProperty], load: LoadConfig) -> None:
    """Reject physically meaningless input before it reaches the linear algebra."""
    if not layers:
        raise ValueError("At least one layer (the subgrade half-space) is required")
    for i, lay in enumerate(layers):
        if not np.isfinite(lay.modulus) or lay.modulus <= 0:
            raise ValueError(f"Layer {i + 1}: modulus must be > 0 MPa (got {lay.modulus!r})")
        if not np.isfinite(lay.poisson) or not (0.0 <= lay.poisson < 0.5):
            raise ValueError(f"Layer {i + 1}: Poisson's ratio must be in [0, 0.5) (got {lay.poisson!r})")
        if i < len(layers) - 1:
            if not np.isfinite(lay.thickness) or lay.thickness < 0:
                raise ValueError(f"Layer {i + 1}: thickness must be >= 0 mm (got {lay.thickness!r})")
            if 0 < lay.thickness < MIN_LAYER_THICKNESS:
                raise ValueError(f"Layer {i + 1}: layers thinner than {MIN_LAYER_THICKNESS:g} mm are not "
                                 f"modelled; enter 0 to omit the layer (got {lay.thickness!r})")
            f = lay.friction_factor
            if not (f >= _BONDED_MIN or f <= _UNBONDED_MAX) or f < 0 or f > 1:
                raise ValueError(
                    f"Layer {i + 1}: friction_factor must be 1 (fully bonded) or 0 "
                    f"(frictionless); partial bond is not modelled (got {f!r})"
                )
    if not np.isfinite(load.load) or load.load <= 0:
        raise ValueError(f"Wheel load must be > 0 N (got {load.load!r})")
    if not np.isfinite(load.pressure) or load.pressure <= 0:
        raise ValueError(f"Contact pressure must be > 0 MPa (got {load.pressure!r})")
    if load.is_dual and (not np.isfinite(load.spacing) or load.spacing <= 0):
        raise ValueError(f"Dual wheels need a positive spacing (got {load.spacing!r})")


def _halfspace_kernel_vec(m, z, q, a, E, nu):
    """
    Closed-form Hankel kernels [uz, ur, sigz, tau] of a homogeneous half-space
    (E, nu) under the uniform circular load (q, a), at depth z, for an array of
    Hankel parameters m. Same sign convention as the layered solver: obtained
    from the A/D half-space solution with sigz(0) = -q_hat, tau(0) = 0, which
    gives D = q_hat/(2*G*m) and A = -(1 - 2*nu)*D.
    """
    G = E / (2.0 * (1.0 + nu))
    q_hat = q * a * bessel_j1(m * a) / m
    D = q_hat / (2.0 * G * m)
    mz = m * z
    e = np.exp(-mz)
    uz = D * (2.0 * (1.0 - nu) + mz) * e
    ur = D * (-(1.0 - 2.0 * nu) + mz) * e
    sz = -q_hat * (1.0 + mz) * e
    tau = -q_hat * mz * e
    return uz, ur, sz, tau


def _halfspace_surface_closed_form(r, q, a, E, nu):
    """
    Exact surface (z = 0) response of a homogeneous half-space under a uniform
    circular load (Boussinesq / Love). Returns (uz, ur, sigz, sigr, sigt, tau).
    uz uses complete elliptic integrals (scipy parameter convention m = k^2);
    ur is the classical (1 - 2nu)(1 + nu) q / (2E) radial movement. sigr and
    sigt follow from the surface strains with sigz prescribed (at r = a the
    one-sided limits are averaged).
    """
    G = E / (2.0 * (1.0 + nu))
    lam = 2.0 * G * nu / (1.0 - 2.0 * nu)
    C = (1.0 - 2.0 * nu) * (1.0 + nu) * q / (2.0 * E)
    r = abs(float(r))
    tol = 1e-9 * a
    if r < a - tol:
        uz = 4.0 * (1.0 - nu ** 2) * q * a / (np.pi * E) * ellipe((r / a) ** 2)
        ur = -C * r
        sz = -q
        er = -C
        et = -C
    elif r > a + tol:
        k2 = (a / r) ** 2
        uz = 4.0 * (1.0 - nu ** 2) * q * r / (np.pi * E) * (ellipe(k2) - (1.0 - k2) * ellipk(k2))
        ur = -C * a * a / r
        sz = 0.0
        er = C * a * a / (r * r)
        et = -C * a * a / (r * r)
    else:  # load edge: average the one-sided limits
        uz = 4.0 * (1.0 - nu ** 2) * q * a / (np.pi * E)
        ur = -C * a
        sz = -0.5 * q
        er = 0.0
        et = -C
    ez = (sz - lam * (er + et)) / (lam + 2.0 * G)
    theta = er + et + ez
    sr = lam * theta + 2.0 * G * er
    st = lam * theta + 2.0 * G * et
    return uz, ur, sz, sr, st, 0.0


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class BurmisterSolver:
    """
    Multi-layer elastic analysis via direct coefficient method.

    For N layers (last = half-space), we have:
      - 4 coefficients per finite layer (A, D, C', B')
      - 2 coefficients for the half-space (A_n, D_n)
      - Total unknowns: 4*(N-1) + 2

    Boundary conditions:
      - Surface (z=0): sigz = -q_hat(m), tau = 0  --> 2 equations
      - Each interface between layer i and i+1:
        continuity of uz, ur, sigz, tau --> 4 equations
      - N-1 interfaces give 4*(N-1) equations
      - Total: 2 + 4*(N-1) = 4*N - 2 = 4*(N-1) + 2  CHECK
    """

    def __init__(self, layers: List[LayerProperty], load: LoadConfig):
        _validate_inputs(layers, load)
        # A zero-thickness finite layer carries no material; keeping it would
        # put two interfaces at the same depth (and make the near-surface
        # decay length 2*h1 - z collapse to zero). Drop it, but keep the bond
        # of the interface it carried: friction_factor describes the interface
        # at the BOTTOM of a layer, and the dropped layer's top and bottom
        # interfaces merge into one plane, which is frictionless if either was.
        kept = []
        for l in layers[:-1]:
            if l.thickness > 0:
                kept.append(l)
            elif kept and l.friction_factor < kept[-1].friction_factor:
                kept[-1] = replace(kept[-1], friction_factor=l.friction_factor)
        layers = kept + [layers[-1]]
        self.layers = layers
        self.load = load
        self.n_layers = len(layers)
        self.a = load.radius

        # Interface depths (absolute)
        self.z_interfaces = [0.0]
        depth = 0.0
        for lay in layers[:-1]:
            depth += lay.thickness
            self.z_interfaces.append(depth)

        # Clamp nu to avoid singularity at nu=0.5
        self.E = np.array([l.modulus for l in layers], dtype=float)
        self.nu = np.array([min(l.poisson, 0.4999) for l in layers], dtype=float)

    def solve(self, eval_points: List[EvalPoint]) -> List[ResponseResult]:
        """Solve for all evaluation points."""
        _validate_points(eval_points)
        if self.load.is_dual:
            return self._solve_dual(eval_points)
        return [self._solve_single(p.z, p.r) for p in eval_points]

    def _solve_dual(self, points: List[EvalPoint]) -> List[ResponseResult]:
        """
        Dual wheel superposition matching IIT Pave convention.

        IIT Pave places eval points along the line connecting wheel centers:
          - Wheel 1 at x=0, Wheel 2 at x=S (full spacing)
          - r=0 → under wheel 1, r=S/2 → midpoint, r=S → under wheel 2
          - d1 = r, d2 = |S - r|

        Both wheels' radial directions align with the x-axis at any point on
        the wheel line, so no stress rotation is needed:
          sigma_r (longitudinal) = sigma_r_w1 + sigma_r_w2
          sigma_t (transverse)   = sigma_t_w1 + sigma_t_w2

        SHEAR (tau_rz) — convention note vs. the original IITPAVE:
          The vertical shear is a VECTOR in the radial direction, so the two
          wheels' contributions carry opposite signs about the symmetry axis
          and are combined WITH a sign-flip (s1, s2 below). On the symmetry
          axis (r = S/2) they cancel to ~0, which is the physically-correct
          elastic value. The original IITPAVE instead sums the two wheels'
          shear WITHOUT the sign-flip, so it reports ~2x the single-wheel
          shear at the axis. This affects ONLY tau_rz (a non-design quantity);
          all IRC criteria use sigma_z/sigma_t/eps_z/eps_t, which are scalar
          superpositions and match IITPAVE to <1%. The dashboard surfaces this
          difference in a tooltip on the tau_rz column. We keep the physically
          correct value here rather than reproduce the IITPAVE summation.
        """
        S = self.load.spacing
        results = []
        for pt in points:
            d1 = abs(pt.r)
            d2 = abs(S - pt.r)

            res1 = self._solve_single(pt.z, d1)
            res2 = self._solve_single(pt.z, d2)

            sig_z = res1.sigma_z + res2.sigma_z
            sig_r = res1.sigma_r + res2.sigma_r
            sig_t = res1.sigma_t + res2.sigma_t
            disp_z = res1.disp_z + res2.disp_z

            # Radial shear/disp: opposite sign contributions between wheels
            s1 = np.sign(pt.r) if abs(pt.r) > 1e-10 else 0.0
            s2 = -np.sign(S - pt.r) if abs(S - pt.r) > 1e-10 else 0.0
            tau_rz = res1.tau_rz * s1 + res2.tau_rz * s2
            disp_r = res1.disp_r * s1 + res2.disp_r * s2

            li = self._get_layer_index(pt.z)
            E_l, nu_l = self.E[li], self.nu[li]
            eps_z = (sig_z - nu_l * (sig_r + sig_t)) / E_l
            eps_r = (sig_r - nu_l * (sig_z + sig_t)) / E_l
            eps_t = (sig_t - nu_l * (sig_z + sig_r)) / E_l

            results.append(ResponseResult(
                z=pt.z, r=pt.r,
                sigma_z=sig_z, sigma_r=sig_r, sigma_t=sig_t,
                tau_rz=tau_rz, disp_z=disp_z, disp_r=disp_r,
                eps_z=eps_z, eps_r=eps_r, eps_t=eps_t,
            ))
        return results

    def _solve_single(self, z: float, r: float) -> ResponseResult:
        """
        Solve for a single evaluation point (z, r) using Hankel inversion.

        For each Hankel parameter m:
          1. Build linear system for layer coefficients
          2. Solve for coefficients
          3. Evaluate state at the point
          4. Accumulate Hankel inversion integrals

        Deep points (decay length >= 0.75a) use the IITPAVE-style interval
        scheme unchanged. Points in the TOP layer shallower than 0.75a split
        the kernel into (layered - top-layer half-space), which decays like
        exp(-m(2h1 - z)) and is integrated numerically, plus the half-space
        part, integrated exactly (closed form at the surface, dense vectorised
        quadrature below it). Shallow points in deeper layers (thin top
        layer) use refined panels extended until exp(-m z) is negligible.
        """
        li = self._get_layer_index(z)
        E_l, nu_l = self.E[li], self.nu[li]
        G_l = E_l / (2.0 * (1.0 + nu_l))
        lam_l = 2.0 * G_l * nu_l / (1.0 - 2.0 * nu_l)
        L2G_l = lam_l + 2.0 * G_l

        z_local = z if li == 0 else z - self.z_interfaces[li]
        a = self.a
        q = self.load.pressure
        r_in = r
        r = abs(float(r))   # axisymmetric: r is a radius

        if li == 0 and z < _NEAR_SURFACE_FACTOR * a:
            z_eval = 0.0 if z < SURFACE_Z_TOL else float(z)
            sums = np.zeros(6)
            if self.n_layers > 1:
                h1 = self.layers[0].thickness

                def diff_kernel(m):
                    st, ok = self._kernel_batch(m, 0, z_eval)
                    hs = np.stack(_halfspace_kernel_vec(m, z_eval, q, a, E_l, nu_l), axis=1)
                    return st - hs, ok

                sums += self._integrate(diff_kernel, r, 2.0 * h1 - z_eval,
                                        lam_l, G_l, L2G_l)
            if z_eval == 0.0:
                uz, ur, sz, sr, st, trz = _halfspace_surface_closed_form(r, q, a, E_l, nu_l)
                sums += np.array([uz, ur, sz, trz, sr, st])
            else:
                m, w = self._refined_nodes(r, z_eval, max_panels=4 * _MAX_REFINED_PANELS)
                hs = _halfspace_kernel_vec(m, z_eval, q, a, E_l, nu_l)
                sums += self._hankel_sums(m, w, *hs, r, lam_l, G_l, L2G_l)
        else:
            sums = self._integrate(lambda m: self._kernel_batch(m, li, z_local),
                                   r, z, lam_l, G_l, L2G_l)

        I_uz, I_ur, I_sz, I_trz, I_sr, I_st = (float(v) for v in sums)

        # Strains from Hooke's law
        eps_z = (I_sz - nu_l * (I_sr + I_st)) / E_l
        eps_r = (I_sr - nu_l * (I_sz + I_st)) / E_l
        eps_t = (I_st - nu_l * (I_sz + I_sr)) / E_l

        return ResponseResult(
            z=z, r=r_in,
            sigma_z=I_sz, sigma_r=I_sr, sigma_t=I_st,
            tau_rz=I_trz, disp_z=I_uz, disp_r=I_ur,
            eps_z=eps_z, eps_r=eps_r, eps_t=eps_t,
        )

    def _integrate(self, kernel_fn, r, z_decay, lam, G, L2G):
        """
        Hankel-invert kernel_fn at radius r. kernel_fn(m_array) returns
        (states (K, 4) = [uz, ur, sigz, tau], ok (K,) bool); nodes whose
        linear system is singular (ok False) are skipped.
        """
        if z_decay >= _NEAR_SURFACE_FACTOR * self.a and abs(r) <= _FAR_FIELD_FACTOR * self.a:
            ms, ws = [], []
            for (m_lo, m_hi, nodes, weights) in self._get_intervals():
                cen = 0.5 * (m_lo + m_hi)
                hlf = 0.5 * (m_hi - m_lo)
                ms.append(cen + hlf * nodes)
                ws.append(hlf * weights)
            m_all = np.concatenate(ms)
            w_all = np.concatenate(ws)
        else:
            m_all, w_all = self._refined_nodes(r, z_decay, max_panels=_MAX_REFINED_PANELS)

        pos = m_all > 0
        m_all, w_all = m_all[pos], w_all[pos]
        if m_all.size == 0:
            return np.zeros(6)
        S, ok = kernel_fn(m_all)
        if not ok.any():
            return np.zeros(6)
        S = S[ok]
        return self._hankel_sums(m_all[ok], w_all[ok],
                                 S[:, 0], S[:, 1], S[:, 2], S[:, 3], r, lam, G, L2G)

    def _refined_nodes(self, r, z_decay, max_panels=None):
        """
        GL8 panels out to exp(-m z_decay) ~ e^-40. Near m = 0 the layered
        kernel varies on the scale 1/(total structure depth), so panels start
        at 0.1/H and grow geometrically (x1.5) up to the oscillation limit
        2/max(a, r) (about a third of a J0/J1 period), which is then kept.
        With max_panels, the constant-width part is widened uniformly if it
        would otherwise exceed that many panels.
        """
        a = self.a
        m_max = max(60.0 / a, _DECAY_TARGET / max(z_decay, 1e-9))
        depth_scale = max(a, self.z_interfaces[-1], z_decay)
        w_cap = _REFINED_PANEL / max(a, abs(r))
        w0 = min(w_cap, 0.1 / depth_scale)
        # geometric ramp w0, 1.5 w0, ... while below w_cap and m_max
        widths = []
        edge, width = 0.0, w0
        while width < w_cap and edge < m_max:
            widths.append(width)
            edge += width
            width = min(w_cap, 1.5 * width)
        if edge < m_max:
            n_const = int(np.ceil((m_max - edge) / w_cap))
            if max_panels is not None and n_const > max_panels:
                if n_const > _MAX_PANEL_WIDENING * max_panels:
                    raise ValueError(
                        f"Evaluation point at r = {r:.0f} mm is too far from a "
                        f"{2 * a:.0f} mm contact area for an accurate Hankel inversion "
                        f"with this layer structure")
                n_const = int(max_panels)
                w_cap = (m_max - edge) / n_const
            widths = np.concatenate([np.asarray(widths, dtype=float),
                                     np.full(n_const, w_cap)])
        edges = np.concatenate([[0.0], np.cumsum(widths)])
        lo = edges[:-1]
        hw = 0.5 * np.diff(edges)
        m = ((lo + hw)[:, None] + hw[:, None] * _GL8_N[None, :]).ravel()
        w = (hw[:, None] * _GL8_W[None, :]).ravel()
        return m, w

    @staticmethod
    def _hankel_sums(m, w, uz_m, ur_m, sigz_m, tau_m, r, lam, G, L2G):
        """
        Vectorised Hankel inversion of the state kernels. Returns
        [uz, ur, sigma_z, tau_rz, sigma_r, sigma_t] at radius r.
        sigma_r / sigma_t are recovered from the constitutive relations:
          duz/dz = (sigz - lam*m*ur)/L2G,  theta = duz/dz + m*ur,
          sigma_r = (lam*theta + 2G*m*ur) J0 - 2G*ur*J1/r,
          sigma_t = lam*theta*J0 + 2G*ur*J1/r.
        """
        mr = m * r
        j0v = bessel_j0(mr)
        j1v = bessel_j1(mr)
        safe = mr > 1e-10
        j1_mr = np.where(safe, j1v / np.where(safe, mr, 1.0), 0.5)
        fac = m * w
        duz_dz = (sigz_m - lam * m * ur_m) / L2G
        theta = duz_dz + m * ur_m
        sr_k = (lam * theta + 2.0 * G * m * ur_m) * j0v - 2.0 * G * ur_m * m * j1_mr
        st_k = lam * theta * j0v + 2.0 * G * ur_m * m * j1_mr
        return np.array([
            np.sum(uz_m * j0v * fac),
            np.sum(ur_m * j1v * fac),
            np.sum(sigz_m * j0v * fac),
            np.sum(tau_m * j1v * fac),
            np.sum(sr_k * fac),
            np.sum(st_k * fac),
        ])

    # ------------------------------------------------------------------
    # Integration intervals (matching IITPAVE structure)
    # ------------------------------------------------------------------

    def _get_intervals(self):
        """Return integration intervals scaled by 1/a."""
        a = self.a
        b = 1.0 / a
        iv = []
        # High-accuracy region (near the peak of the integrand)
        for b0, b1 in [(0, 0.5), (0.5, 1), (1, 2), (2, 4), (4, 6), (6, 8)]:
            iv.append((b0 * b, b1 * b, GL10_N, GL10_W))
        # Medium-accuracy region
        for b0, b1 in [(8, 12), (12, 16), (16, 20)]:
            iv.append((b0 * b, b1 * b, GL6_N, GL6_W))
        # Tail region (integrand is small)
        for b0, b1 in [(20, 28), (28, 40), (40, 60)]:
            iv.append((b0 * b, b1 * b, GL4_N, GL4_W))
        return iv

    def _get_layer_index(self, z: float) -> int:
        """Find which layer contains depth z."""
        for i in range(1, len(self.z_interfaces)):
            if z <= self.z_interfaces[i] + 1e-6:
                return i - 1
        return self.n_layers - 1

    # ------------------------------------------------------------------
    # Build and solve the coefficient systems for an array of m (batched)
    # ------------------------------------------------------------------

    def _kernel_batch(self, m, layer_eval, z_local_eval):
        """
        Vectorised _kernel_at_m: the same linear system, assembled for every
        m in the array and solved as a batch. Returns (states (K, 4), ok (K,))
        where ok is False for nodes whose system is singular (those are
        skipped, as _kernel_at_m returning None was).
        """
        m = np.asarray(m, dtype=float)
        K = m.size
        states = np.zeros((K, 4))
        ok = np.ones(K, dtype=bool)
        for s in range(0, K, _KERNEL_CHUNK):
            sl = slice(s, min(K, s + _KERNEL_CHUNK))
            states[sl], ok[sl] = self._kernel_chunk(m[sl], layer_eval, z_local_eval)
        return states, ok

    def _kernel_chunk(self, m, layer_eval, z_local_eval):
        N = self.n_layers
        n_unknowns = 4 * (N - 1) + 2
        K = m.size
        A = np.zeros((K, n_unknowns, n_unknowns))
        b = np.zeros((K, n_unknowns))
        q_hat = self.load.pressure * self.a * bessel_j1(m * self.a) / m

        row = 0
        if N == 1:
            M_hs_surf = _halfspace_state_matrix_vec(m, 0.0, self.E[0], self.nu[0])
            A[:, 0, 0:2] = M_hs_surf[:, 2, :]
            b[:, 0] = -q_hat
            A[:, 1, 0:2] = M_hs_surf[:, 3, :]
        else:
            M_top = _finite_state_matrix_vec(m, 0.0, self.layers[0].thickness,
                                             self.E[0], self.nu[0])
            A[:, 0, 0:4] = M_top[:, 2, :]
            b[:, 0] = -q_hat
            A[:, 1, 0:4] = M_top[:, 3, :]
            row = 2
            for iface in range(N - 1):
                h_i = self.layers[iface].thickness
                M_bot = _finite_state_matrix_vec(m, h_i, h_i, self.E[iface], self.nu[iface])
                ca = 4 * iface
                if iface < N - 2:
                    M_nb = _finite_state_matrix_vec(m, 0.0, self.layers[iface + 1].thickness,
                                                    self.E[iface + 1], self.nu[iface + 1])
                    cb, nb = 4 * (iface + 1), 4
                else:
                    M_nb = _halfspace_state_matrix_vec(m, 0.0, self.E[N - 1], self.nu[N - 1])
                    cb, nb = 4 * (N - 1), 2
                if self.layers[iface].friction_factor >= _BONDED_MIN:
                    for comp in range(4):
                        A[:, row, ca:ca + 4] = M_bot[:, comp, :]
                        A[:, row, cb:cb + nb] = -M_nb[:, comp, :]
                        row += 1
                else:  # frictionless: uz, sigz continuous; tau = 0 on both faces
                    for comp in (0, 2):
                        A[:, row, ca:ca + 4] = M_bot[:, comp, :]
                        A[:, row, cb:cb + nb] = -M_nb[:, comp, :]
                        row += 1
                    A[:, row, ca:ca + 4] = M_bot[:, 3, :]
                    row += 1
                    A[:, row, cb:cb + nb] = M_nb[:, 3, :]
                    row += 1

        ok = np.ones(K, dtype=bool)
        try:
            coeffs = np.linalg.solve(A, b[..., None])[..., 0]
        except np.linalg.LinAlgError:
            coeffs = np.zeros((K, n_unknowns))
            for k in range(K):
                try:
                    coeffs[k] = np.linalg.solve(A[k], b[k])
                except np.linalg.LinAlgError:
                    ok[k] = False

        if layer_eval < N - 1:
            ci = 4 * layer_eval
            M = _finite_state_matrix_vec(m, z_local_eval, self.layers[layer_eval].thickness,
                                         self.E[layer_eval], self.nu[layer_eval])
            st = np.einsum("kij,kj->ki", M, coeffs[:, ci:ci + 4])
        else:
            ci = 4 * (N - 1)
            M = _halfspace_state_matrix_vec(m, z_local_eval, self.E[N - 1], self.nu[N - 1])
            st = np.einsum("kij,kj->ki", M, coeffs[:, ci:ci + 2])
        return st, ok

    # ------------------------------------------------------------------
    # Build and solve the coefficient system for a given m
    # ------------------------------------------------------------------

    def _kernel_at_m(self, m, layer_eval, z_local_eval):
        """
        For a given Hankel parameter m:
          1. Assemble the linear system for all layer coefficients.
          2. Solve for coefficients.
          3. Evaluate the state [uz, ur, sigz, tau] at the requested point.

        Returns [uz, ur, sigz, tau] or None on failure.
        """
        N = self.n_layers
        n_unknowns = 4 * (N - 1) + 2

        A_mat = np.zeros((n_unknowns, n_unknowns))
        b_vec = np.zeros(n_unknowns)

        # Load Hankel transform: q_hat = p * a * J1(m*a) / m
        q_hat = self.load.pressure * self.a * bessel_j1(m * self.a) / m

        def idx_finite(i):
            """Index of first coefficient for finite layer i."""
            return 4 * i

        def idx_hs():
            """Index of first coefficient for the half-space."""
            return 4 * (N - 1)

        # ---- Build the system ----
        row = 0

        if N == 1:
            # Special case: single half-space (Boussinesq)
            M_hs_surf = _halfspace_state_matrix(m, 0.0, self.E[0], self.nu[0])
            ci = 0  # only 2 unknowns

            # sigz(0) = -q_hat
            A_mat[row, ci:ci+2] = M_hs_surf[2, :]
            b_vec[row] = -q_hat
            row += 1

            # tau(0) = 0
            A_mat[row, ci:ci+2] = M_hs_surf[3, :]
            b_vec[row] = 0.0
            row += 1
        else:
            # --- Surface BCs at z=0 (top of layer 0, finite) ---
            M_top = _finite_state_matrix(m, 0.0, self.layers[0].thickness,
                                          self.E[0], self.nu[0])
            ci = idx_finite(0)

            # sigz(0) = -q_hat
            A_mat[row, ci:ci+4] = M_top[2, :]
            b_vec[row] = -q_hat
            row += 1

            # tau(0) = 0
            A_mat[row, ci:ci+4] = M_top[3, :]
            b_vec[row] = 0.0
            row += 1

            # --- Interface continuity ---
            for iface in range(N - 1):
                h_i = self.layers[iface].thickness
                E_i, nu_i = self.E[iface], self.nu[iface]

                # State at bottom of layer iface (z = h_i)
                M_bot = _finite_state_matrix(m, h_i, h_i, E_i, nu_i)
                ci_above = idx_finite(iface)

                if iface < N - 2:
                    # Finite layer below
                    E_below = self.E[iface + 1]
                    nu_below = self.nu[iface + 1]
                    h_below = self.layers[iface + 1].thickness
                    M_top_below = _finite_state_matrix(m, 0.0, h_below,
                                                        E_below, nu_below)
                    ci_below = idx_finite(iface + 1)

                    # Continuity: state_bot(i) = state_top(i+1)
                    friction = self.layers[iface].friction_factor
                    
                    if friction >= _BONDED_MIN:  # fully bonded
                        for comp in range(4):
                            A_mat[row, ci_above:ci_above+4] = M_bot[comp, :]
                            A_mat[row, ci_below:ci_below+4] = -M_top_below[comp, :]
                            b_vec[row] = 0.0
                            row += 1
                    else:  # frictionless (friction == 0; partial bond rejected upstream)
                        # uz continuous
                        A_mat[row, ci_above:ci_above+4] = M_bot[0, :]
                        A_mat[row, ci_below:ci_below+4] = -M_top_below[0, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # sigz continuous
                        A_mat[row, ci_above:ci_above+4] = M_bot[2, :]
                        A_mat[row, ci_below:ci_below+4] = -M_top_below[2, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # tau_bot = 0
                        A_mat[row, ci_above:ci_above+4] = M_bot[3, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # tau_top_below = 0
                        A_mat[row, ci_below:ci_below+4] = M_top_below[3, :]
                        b_vec[row] = 0.0
                        row += 1

                else:
                    # Half-space below
                    M_hs_top = _halfspace_state_matrix(m, 0.0,
                                                        self.E[N-1], self.nu[N-1])
                    ci_below = idx_hs()
                    friction = self.layers[iface].friction_factor

                    if friction >= _BONDED_MIN:
                        for comp in range(4):
                            A_mat[row, ci_above:ci_above+4] = M_bot[comp, :]
                            A_mat[row, ci_below:ci_below+2] = -M_hs_top[comp, :]
                            b_vec[row] = 0.0
                            row += 1
                    else:
                        # uz continuous
                        A_mat[row, ci_above:ci_above+4] = M_bot[0, :]
                        A_mat[row, ci_below:ci_below+2] = -M_hs_top[0, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # sigz continuous
                        A_mat[row, ci_above:ci_above+4] = M_bot[2, :]
                        A_mat[row, ci_below:ci_below+2] = -M_hs_top[2, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # tau_bot = 0
                        A_mat[row, ci_above:ci_above+4] = M_bot[3, :]
                        b_vec[row] = 0.0
                        row += 1
                        
                        # tau_top_below = 0
                        A_mat[row, ci_below:ci_below+2] = M_hs_top[3, :]
                        b_vec[row] = 0.0
                        row += 1

        # ---- Solve ----
        try:
            coeffs_all = np.linalg.solve(A_mat, b_vec)
        except np.linalg.LinAlgError:
            return None

        # ---- Evaluate state at the requested point ----
        if layer_eval < N - 1:
            ci = idx_finite(layer_eval)
            c = coeffs_all[ci:ci+4]
            h_eval = self.layers[layer_eval].thickness
            return _eval_state_finite(m, z_local_eval, h_eval,
                                       self.E[layer_eval], self.nu[layer_eval], c)
        else:
            ci = idx_hs()
            c = coeffs_all[ci:ci+2]
            return _eval_state_halfspace(m, z_local_eval,
                                          self.E[N-1], self.nu[N-1], c)


# ---------------------------------------------------------------------------
# High-level API (for web/optimizer integration)
# ---------------------------------------------------------------------------

def analyze_pavement(layers_data, load_data, eval_points_data):
    """
    High-level analysis function.

    layers_data: list of dicts with 'modulus', 'poisson', 'thickness', 'friction_factor'(opt)
    load_data: dict with 'load', 'pressure', 'is_dual', 'spacing'
    eval_points_data: list of dicts with 'z', 'r'
    """
    layers = [
        LayerProperty(ld['modulus'], ld['poisson'], ld['thickness'], ld.get('friction_factor', 1.0))
        for ld in layers_data
    ]
    load = LoadConfig(
        load=load_data['load'],
        pressure=load_data['pressure'],
        is_dual=load_data.get('is_dual', False),
        spacing=load_data.get('spacing', 310.0),
    )
    points = [EvalPoint(ep['z'], ep['r']) for ep in eval_points_data]

    solver = BurmisterSolver(layers, load)
    results = solver.solve(points)

    return [
        {
            "z": res.z, "r": res.r,
            "sigma_z": res.sigma_z, "sigma_r": res.sigma_r,
            "sigma_t": res.sigma_t, "tau_rz": res.tau_rz,
            "disp_z": res.disp_z, "disp_r": res.disp_r,
            "eps_z": res.eps_z, "eps_r": res.eps_r, "eps_t": res.eps_t,
        }
        for res in results
    ]
