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
from scipy.special import j0 as bessel_j0, j1 as bessel_j1
from dataclasses import dataclass
from typing import List


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
        """
        li = self._get_layer_index(z)
        E_l, nu_l = self.E[li], self.nu[li]
        G_l = E_l / (2.0 * (1.0 + nu_l))
        lam_l = 2.0 * G_l * nu_l / (1.0 - 2.0 * nu_l)
        L2G_l = lam_l + 2.0 * G_l

        z_local = z if li == 0 else z - self.z_interfaces[li]

        I_uz = I_ur = I_sz = I_trz = I_sr = I_st = 0.0

        for (m_lo, m_hi, nodes, weights) in self._get_intervals():
            cen = 0.5 * (m_lo + m_hi)
            hlf = 0.5 * (m_hi - m_lo)
            for i in range(len(nodes)):
                mv = cen + hlf * nodes[i]
                if mv <= 0:
                    continue
                w = hlf * weights[i]

                state = self._kernel_at_m(mv, li, z_local)
                if state is None:
                    continue

                uz_m, ur_m, sigz_m, tau_m = state

                mr = mv * r
                j0v = bessel_j0(mr)
                j1v = bessel_j1(mr)
                j1_mr = j1v / mr if mr > 1e-10 else 0.5

                fac = mv * w
                I_uz += uz_m * j0v * fac
                I_ur += ur_m * j1v * fac
                I_sz += sigz_m * j0v * fac
                I_trz += tau_m * j1v * fac

                # sigma_r and sigma_t from constitutive relations
                # Recover duz/dz from sigz: sigz = L2G*duz/dz + lam*m*ur
                # => duz/dz = (sigz - lam*m*ur) / L2G
                duz_dz_m = (sigz_m - lam_l * mv * ur_m) / L2G_l

                # Volumetric strain: theta = duz/dz + m*ur (in Hankel domain)
                theta = duz_dz_m + mv * ur_m

                # sigma_r in physical: needs both J0 and J1/r terms
                # sigma_r = lam*theta + 2G*(dur/dr)
                # In Hankel: dur/dr part -> m*ur for J0 term, -ur for J1/r term
                sr_j0 = lam_l * theta + 2.0 * G_l * mv * ur_m
                sr_j1r = -2.0 * G_l * ur_m
                st_j0 = lam_l * theta
                st_j1r = 2.0 * G_l * ur_m

                I_sr += (sr_j0 * j0v + sr_j1r * mv * j1_mr) * fac
                I_st += (st_j0 * j0v + st_j1r * mv * j1_mr) * fac

        # Strains from Hooke's law
        eps_z = (I_sz - nu_l * (I_sr + I_st)) / E_l
        eps_r = (I_sr - nu_l * (I_sz + I_st)) / E_l
        eps_t = (I_st - nu_l * (I_sz + I_sr)) / E_l

        return ResponseResult(
            z=z, r=r,
            sigma_z=I_sz, sigma_r=I_sr, sigma_t=I_st,
            tau_rz=I_trz, disp_z=I_uz, disp_r=I_ur,
            eps_z=eps_z, eps_r=eps_r, eps_t=eps_t,
        )

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
                    
                    if friction >= 0.999: # Fully bonded
                        for comp in range(4):
                            A_mat[row, ci_above:ci_above+4] = M_bot[comp, :]
                            A_mat[row, ci_below:ci_below+4] = -M_top_below[comp, :]
                            b_vec[row] = 0.0
                            row += 1
                    else: # Fully unbonded (friction == 0)
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

                    if friction >= 0.999:
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
