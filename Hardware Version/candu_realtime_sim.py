#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CANDU Real-Time Simulator (Fission Vision Capstone Team)
===============================================================================
Developed By: Sarah Khalid (Engineering Physics Student | University of Saskatchewan)
Last Updated: April 12, 2026

PURPOSE
===============================================================================
This module implements the core real-time physics / controls engine used by the
Fission Vision capstone team for an educational CANDU-style reactor simulator.

It is written as a lightweight Python back end that can be:
    1) run directly from the console for testing, or
    2) imported into a GUI application (PyQt6) that provides
       buttons, sliders, control inputs, and plots.

The code is intentionally structured around a small number of state containers
and update functions so that future contributors can:
    - swap in more detailed physics models,
    - connect external UI widgets,
    - add logging / replay,
    - replace the Matplotlib plotter,
    - or route the simulator through hardware I/O.

===============================================================================
HIGH-LEVEL MODEL OVERVIEW
===============================================================================
The simulator combines five simplified submodels:

1) Point kinetics (fast neutronic response)
   ---------------------------------------------------------------------------
   One effective delayed-neutron group is used:
       dP/dt = ((rho - beta_eff) / Lambda) * P + lambda_d * C
       dC/dt = (beta_eff / Lambda) * P - lambda_d * C

   where:
       P        = normalized neutron power [-], with P = 1.0 at full power
       C        = effective delayed-neutron precursor state [-]
       rho      = total reactivity [delta-k/k]
       beta_eff = effective delayed neutron fraction [delta-k/k]
       Lambda   = prompt neutron generation time [s]
       lambda_d = effective precursor decay constant [1/s]

   The 2-state kinetics system is advanced exactly over each substep using the
   closed-form matrix exponential of the 2x2 state matrix. This is more stable
   than simple forward-Euler time stepping and works well when the simulator is
   accelerated in time.

2) Thermal feedback (fuel + moderator)
   ---------------------------------------------------------------------------
   A simplified temperature-feedback law is used:
       rho_fb = alpha_ftc * (Tf - Tf0) + alpha_mtc * (Tm - Tm0)

   where:
       Tf = effective fuel temperature [°C]
       Tm = effective moderator / coolant temperature proxy [°C]

   Tf and Tm are each driven toward power-dependent steady-state values using
   exact first-order lag updates:
       x(t + dt) = x_ss + (x(t) - x_ss) * exp(-dt / tau)

3) Xenon / poison dynamics (slow)
   ---------------------------------------------------------------------------
   The iodine-xenon effect is represented by normalized states:
       I_hat, Xe_hat

   The implementation uses:
       I_hat -> slow first-order follow of power
       Xe_hat -> slow first-order follow of Xe_eq
       Xe_eq = 1 + xe_eq_gain * I_hat

   This creates the intended educational behaviour:
       - at power, xenon slowly builds in,
       - xenon adds negative reactivity,
       - the effect is subtle at 1x speed but more visible when the simulator
         is accelerated.

4) Fuel burnup / refuelling reactivity inventory (slow)
   ---------------------------------------------------------------------------
   Long-term reactivity from burnup and refuelling is lumped into:
       rho_fuel_mk  [mk]

   Updated using:
       d(rho_fuel_mk)/dt = burn_rate_full_mk_per_s * (refuel_rate_cmd - P)

   Interpretation:
       - If refuelling command matches power, long-term reactivity stays near
         steady.
       - If refuelling is too low, rho_fuel_mk drifts negative.
       - If refuelling is increased, rho_fuel_mk recovers over time.

   This preserves the intended qualitative distinction:
       * LZC / ADJ / MCA act quickly
       * refuelling acts slowly but dominates the long-term trend

5) Steam-generator / turbine pressure proxy
   ---------------------------------------------------------------------------
   Pressure is not a full thermodynamic model. Instead, it is a simple
   first-order proxy tied to power:
       p_eq = p_min + (p_base - p_min) * P
   and then:
       p_turb(t + dt) = first_order_exact(p_turb, p_eq, tau_p, dt)

   This is sufficient for visualization and operator feedback.

===============================================================================
USER MANUAL (CONSOLE / TEST MODE)
===============================================================================
Available commands that you can type directly on the console to observe changes on Matplotlib:

    help
    status
    pause sim
    resume sim
    set safety on|off
    set speed <1..3000>
    set goal <0..1.2>
    set lzc <0..100>
    set adj <0..1>
    set mca <0..1>
    set refuel <0..2.0>
    trip sds1
    trip sds2
    reset sds
    reset steady
    quit

Command meanings:
    speed
        Reactor seconds per wall-clock second. Example:
            speed = 60 means 1 real second = 1 reactor minute.

    goal
        Operator target power fraction (to make it a game-like experience)

    lzc
        Liquid-zone average fill level [%].
        50% is neutral.
        Lower fill -> positive reactivity -> power tends to rise.
        Higher fill -> negative reactivity -> power tends to fall.

    adj
        Adjuster-rod withdrawal fraction [0..1].
        Higher value -> more positive reactivity.

    mca
        Mechanical control absorber insertion fraction [0..1].
        Higher value -> more negative reactivity.

    refuel
        Continuous long-term refuelling command [0..2].
        This is intentionally continuous rather than discrete so it maps well to
        future GUI sliders or analogue hardware controls.

    safety
        Enables or disables automatic stepback / shutdown logic.

    trip sds1 / trip sds2
        Manual shutdown request.

    reset sds
        Clears shutdown latches only when power is below 1% FP.

    reset steady
        Full reinitialization to the nominal startup state.

===============================================================================
ENGINEERING NOTES FOR FUTURE DEVELOPERS
===============================================================================
1) This file is best thought of as the "simulation engine".
   The PyQt6 GUI:
       - owns an instance of CanduRealtimeSim,
       - reads from the history buffers,
       - writes to the Controls object through thread-safe commands,
       - and calls the simulator's existing methods rather than duplicating logic.

2) Current concurrency model:
       - one physics loop thread,
       - one console-input thread (for testing),
       - optional Matplotlib plot loop if _plot() is called.

   For a PyQt6 application, we:
       - disable the console loop,
       - not use _plot(),
       - and instead connect a QTimer to redraw from the history buffers.

3) Known simplifications:
       - one delayed-neutron group instead of six,
       - lumped thermal states instead of detailed HTS / SG thermodynamics,
       - normalized poison states instead of full iodine/xenon number densities,
       - simplified shutdown logic compared with plant-grade 2-out-of-3 voting.


===============================================================================
"""

from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict

import numpy as np

# Matplotlib is optional from the simulator-engine perspective.
# It is used only by the built-in test plotter in _plot().
try:
    import matplotlib

    # Use a live GUI backend when possible so the built-in plot updates in real
    # time. If the environment already uses an inline backend, leave it alone.
    if "inline" not in matplotlib.get_backend().lower():
        matplotlib.use("TkAgg")
except Exception:
    pass

import matplotlib.pyplot as plt


# =============================================================================
# PARAMETER CONTAINER
# =============================================================================

@dataclass
class PlantParams:
    """
    Collection of fixed plant / model parameters.

    These values are intentionally centralized so future contributors can retune
    the simulator without digging through the update logic.

    Units and conventions
    ---------------------
    - Power P is normalized to full power:
          P = 1.0  -> 100 %FP
          P = 0.5  -> 50  %FP

    - Thermal power conversion:
          Q_th = P * Q_th_full_MW

    - Electric power conversion:
          P_e = eta_electric * Q_th

    - Reactivity inputs from devices are stored in mk (milli-k) for readability
      and then converted to delta-k/k when used in kinetics:
          1 mk = 1e-3 delta-k/k

    - Time constants are in reactor seconds, not wall-clock seconds.

    Parameter ranges
    ----------------
    These are not all enforced here, but the command handler clamps the main
    operator-facing controls to practical ranges.
    """

    # ---------------------------------------------------------------------
    # Power scaling
    # ---------------------------------------------------------------------
    Q_th_full_MW: float = 2832.0
    """Full-power thermal rating [MW_th]."""

    eta_electric: float = 0.289
    """Thermal-to-electric conversion factor [-]."""

    # ---------------------------------------------------------------------
    # One-group point kinetics parameters
    # ---------------------------------------------------------------------
    beta_eff: float = 0.0055
    """Effective delayed neutron fraction [delta-k/k]."""

    Lambda_s: float = 1.0e-3
    """Prompt neutron generation time [s]."""

    lambda_d_s: float = 0.08
    """Effective delayed-neutron precursor decay constant [1/s]."""

    # ---------------------------------------------------------------------
    # Device worths [mk]
    # ---------------------------------------------------------------------
    w_lzc_total_mk: float = 5.0
    """Total liquid-zone worth around nominal operating band [mk]."""

    w_adj_total_mk: float = 15.0
    """Total adjuster worth [mk]."""

    w_mca_total_mk: float = -9.0
    """Total MCA worth [mk]. Negative because insertion reduces reactivity."""

    # ---------------------------------------------------------------------
    # Thermal feedback coefficients
    # ---------------------------------------------------------------------
    alpha_ftc_mk_per_C: float = -0.0144
    """Fuel temperature coefficient [mk / °C]."""

    alpha_mtc_mk_per_C: float = +0.08
    """Moderator temperature coefficient [mk / °C]."""

    Tf0_C: float = 637.5
    """Reference fuel temperature [°C]."""

    Tm0_C: float = 70.0
    """Reference moderator temperature [°C]."""

    # ---------------------------------------------------------------------
    # Simplified thermal model
    # ---------------------------------------------------------------------
    Tin_C: float = 265.0
    """Coolant / moderator inlet temperature proxy [°C]."""

    dTcore_full_C: float = 45.0
    """Approximate core temperature rise at full power [°C]."""

    dT_fc_full_C: float = 350.0
    """Approximate fuel-over-coolant rise at full power [°C]."""

    Tm_slope_C_per_P: float = 2.0
    """Moderator temperature sensitivity to normalized power [°C / P]."""

    tau_f_s: float = 10.0
    """Fuel-temperature lag time constant [s]."""

    tau_m_s: float = 300.0
    """Moderator-temperature lag time constant [s]."""

    # ---------------------------------------------------------------------
    # Pressure proxy
    # ---------------------------------------------------------------------
    p_base_MPa: float = 4.70
    """Nominal full-power steam-generator / turbine pressure [MPa]."""

    p_min_MPa: float = 0.50
    """Low-power pressure floor for the pressure proxy [MPa]."""

    tau_p_s: float = 45.0
    """Pressure-response time constant [s]."""

    # ---------------------------------------------------------------------
    # Poison model
    # ---------------------------------------------------------------------
    tau_I_s: float = 6.57 * 3600.0
    """Iodine-like time constant [s]."""

    tau_Xe_s: float = 9.14 * 3600.0
    """Xenon-like time constant [s]."""

    xe_eq_gain: float = 0.06
    """
    Xenon equilibrium gain [-].

    Xe_eq = 1 + xe_eq_gain * I_hat

    Larger values produce a stronger slow decline due to xenon buildup.
    """

    w_xe_mk: float = 22.0
    """Xenon reactivity worth [mk per unit Xe_hat deviation from 1]."""

    # ---------------------------------------------------------------------
    # Fuel / burnup / refuelling
    # ---------------------------------------------------------------------
    burn_rate_full_mk_per_s: float = 1.0 / 86400.0
    """
    Long-term burnup / refuelling sensitivity [mk/s at full-power mismatch].

    With:
        d(rho_fuel_mk)/dt = burn_rate_full_mk_per_s * (refuel_rate_cmd - P)
    """

    rho_fuel_limit_mk: float = 20.0
    """Clamp limit for the slow fuel-reactivity inventory state [mk]."""

    # ---------------------------------------------------------------------
    # Protection thresholds
    # ---------------------------------------------------------------------
    stepback_lograte_s: float = 0.08
    """Stepback threshold on d(ln P)/dt [1/s]."""

    sds1_lograte_s: float = 0.10
    """SDS1 threshold on d(ln P)/dt [1/s]."""

    sds2_lograte_s: float = 0.15
    """SDS2 threshold on d(ln P)/dt [1/s]."""

    rop_sds1_FP: float = 1.12
    """SDS1 overpower threshold [fraction of full power]."""

    rop_sds2_FP: float = 1.18
    """SDS2 overpower threshold [fraction of full power]."""

    Tf_warn_C: float = 720.0
    """Temperature warning threshold [°C]."""

    Tf_sds1_C: float = 800.0
    """SDS1 temperature-trip threshold [°C]."""

    Tf_sds2_C: float = 900.0
    """SDS2 temperature-trip threshold [°C]."""

    rho_stepback_mk: float = -10.0
    """Negative reactivity inserted by stepback logic [mk]."""

    rho_sds1_mk: float = -120.0
    """Negative reactivity inserted by SDS1 [mk]."""

    rho_sds2_mk: float = -500.0
    """Negative reactivity inserted by SDS2 [mk]."""

    # ---------------------------------------------------------------------
    # Safety-off 'explosion' thresholds (educational / game logic)
    # ---------------------------------------------------------------------
    Tf_explode_C: float = 1200.0
    """Fuel temperature threshold for simulated explosion [°C]."""

    P_explode_FP: float = 3.0
    """Power threshold for simulated explosion [fraction of full power]."""

    # ---------------------------------------------------------------------
    # Time stepping / buffering
    # ---------------------------------------------------------------------
    dt_wall_s: float = 0.05
    """Main wall-clock loop period [s]. 20 Hz update rate."""

    history_wall_s: float = 180.0
    """History buffer length for plots [wall-clock seconds]."""

    max_speed: float = 3600.0
    """Maximum reactor-time speed multiplier [reactor s / wall s]."""

    dt_max_reactor_s: float = 1.0
    """
    Maximum reactor-time substep [s].

    The simulator subdivides a large accelerated step into smaller physics
    substeps to avoid losing stability / responsiveness.
    """


# =============================================================================
# OPERATOR CONTROLS / COMMAND STATE
# =============================================================================

@dataclass
class Controls:
    """
    Mutable control inputs and command flags.

    This object represents the current operator / GUI state rather than the
    physical reactor state.
    """

    safety_enabled: bool = True
    """True -> enable automatic protection logic."""

    paused: bool = False
    """True -> freeze reactor-time advancement while preserving the program."""

    time_scale: float = 1.0
    """
    Reactor-time speed multiplier [reactor s / wall s].

    Typical range enforced by command handler: 1 .. PlantParams.max_speed
    """

    goal_frac: float = 1.0
    """Visual goal line on the electric-power plot [fraction of full power]."""

    lzc_fill_pct: float = 50.0
    """
    Average liquid-zone fill [%].

    Practical command range:
        0   -> maximally drained (positive reactivity)
        50  -> neutral reference
        100 -> maximally filled (negative reactivity)
    """

    adj_out_frac: float = 0.0
    """
    Adjuster withdrawal fraction [-].

    Practical range:
        0 -> inserted / no positive worth applied
        1 -> fully withdrawn / max positive worth applied
    """

    mca_in_frac: float = 0.0
    """
    Mechanical control absorber insertion fraction [-].

    Practical range:
        0 -> withdrawn
        1 -> fully inserted
    """

    refuel_rate_cmd: float = 0.9960
    """
    Long-term refuelling command [-].

    Practical range:
        0 .. 2.0

    Values below current power cause long-term negative reactivity drift;
    values above current power cause long-term positive recovery.
    """

    trip_sds1: bool = False
    """Manual latch request for SDS1."""

    trip_sds2: bool = False
    """Manual latch request for SDS2."""

    request_reset_steady: bool = False
    """Full simulator reset request."""

    request_reset_sds: bool = False
    """Request to clear shutdown latches if conditions permit."""

    event_status: list[str] = field(default_factory=list)
    


# =============================================================================
# REACTOR STATE VECTOR
# =============================================================================

@dataclass
class ReactorState:
    """
    Dynamic reactor state variables.

    These are the internal physics states advanced by the simulator.
    """

    P: float = 1.0
    """Normalized neutron power [-]."""

    C: float = 0.0
    """Effective delayed-neutron precursor state [-]."""

    I_hat: float = 1.0
    """Normalized iodine-like poison state [-]."""

    Xe_hat: float = 1.0
    """Normalized xenon-like poison state [-]."""

    rho_fuel_mk: float = 0.0
    """Slow fuel / burnup / refuelling reactivity inventory [mk]."""

    Tf: float = 637.5
    """Effective fuel temperature [°C]."""

    Tm: float = 70.0
    """Effective moderator / coolant temperature proxy [°C]."""

    p_turb: float = 4.70
    """Steam-generator / turbine pressure proxy [MPa]."""

    stepback_active: bool = False
    """True if the automatic stepback logic is latched active."""

    sds1_active: bool = False
    """True if SDS1 is latched."""

    sds2_active: bool = False
    """True if SDS2 is latched."""

    exploded: bool = False
    """True if the safety-off meltdown condition has been reached."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clamp(x: float, lo: float, hi: float) -> float:
    """
    Clamp a scalar into the closed interval [lo, hi].

    Parameters
    ----------
    x : float
        Input value.
    lo : float
        Lower bound.
    hi : float
        Upper bound.

    Returns
    -------
    float
        Clamped value.
    """
    return max(lo, min(hi, x))


def mk_to_dk(mk: float) -> float:
    """
    Convert milli-k [mk] to delta-k/k.

    1 mk = 1e-3 delta-k/k
    """
    return mk * 1e-3


def fmt_pct(P: float) -> str:
    """
    Format normalized power as a fixed-width percent-of-full-power string.
    """
    return f"{100.0 * P:6.1f}%"


def expm2x2(M: np.ndarray) -> np.ndarray:
    """
    Compute the exact matrix exponential exp(M) for a 2x2 matrix.

    This helper is used to integrate the 1-group point-kinetics system exactly
    over a finite time step, which is preferable to explicit Euler for a stiff
    prompt-neutron / delayed-neutron system.

    Parameters
    ----------
    M : np.ndarray shape (2, 2)
        2x2 state matrix.

    Returns
    -------
    np.ndarray shape (2, 2)
        Exact matrix exponential exp(M).
    """
    tr = M[0, 0] + M[1, 1]
    det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
    s = tr / 2.0
    delta = np.sqrt((s * s - det) + 0j)
    I = np.eye(2, dtype=complex)
    Ms = M - s * I

    if abs(delta) < 1e-12:
        E = np.exp(s) * (I + Ms)
    else:
        E = np.exp(s) * (np.cosh(delta) * I + (np.sinh(delta) / delta) * Ms)

    return np.real_if_close(E, tol=1e-10).astype(float)


def first_order_exact(x: float, x_ss: float, tau: float, dt: float) -> float:
    """
    Exact discrete-time update for a first-order lag.

    Model:
        dx/dt = (x_ss - x) / tau

    Exact solution over one interval dt:
        x(t + dt) = x_ss + (x(t) - x_ss) * exp(-dt / tau)

    Parameters
    ----------
    x : float
        Current state.
    x_ss : float
        Steady-state target value.
    tau : float
        Time constant [s].
    dt : float
        Time step [s].

    Returns
    -------
    float
        Updated state.
    """
    if tau <= 0:
        return x_ss
    return x_ss + (x - x_ss) * np.exp(-dt / tau)


def fmt_reactor_time(seconds: float) -> str:
    """
    Format elapsed reactor time in HH:MM:SS.
    """
    s = max(0.0, seconds)
    h = int(s // 3600)
    m = int((s - 3600 * h) // 60)
    sec = int(s - 3600 * h - 60 * m)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# =============================================================================
# MAIN SIMULATOR CLASS
# =============================================================================

class CanduRealtimeSim:
    """
    Core real-time reactor simulator.

    Purpose
    ----------------
    - Own the model parameters, controls, and dynamic reactor state.
    - Advance the reactor state in real time.
    - Manage pause / reset / trip logic.
    - Maintain history buffers for plotting or GUI display.
    - Provide console commands for test-mode interaction.
    - Optionally provide a built-in Matplotlib plotter.

    Architecture notes
    ------------------
        - self.ctrl stores user / operator commands
        - self.x stores physical state
        - self.*_hist buffers store time traces
        - _physics_loop() advances the simulation
        - _plot() is optional and may be replaced by a GUI layer
    """

    def __init__(self, p: PlantParams):
        """
        Construct a simulator instance.

        Parameters
        ----------
        p : PlantParams
            Immutable model parameter set.
        """
        self.p = p
        self.ctrl = Controls()
        self.x = ReactorState()

        # Thread / runtime bookkeeping
        self._running = True
        self._lock = threading.Lock()

        # Wall-clock time references
        self._t0_wall = time.time()
        self._pause_start = None
        self._paused_wall_time = 0.0

        # Reactor-time state
        self._t_reactor = 0.0

        # Previous power sample for log-rate calculation
        self._prev_P = 1.0
        self._lograte = 0.0

        # Human-readable status text
        self._warning_text = ""
        self._status_label = "STATUS: GOOD"

        # Event throttling dictionary
        self._last_event: Dict[str, float] = {}

        # Fixed-length history buffers used by the built-in plotter and suitable
        # for future GUI plotting widgets.
        n = int(self.p.history_wall_s / self.p.dt_wall_s) + 1
        self.t_wall_hist: Deque[float] = deque(maxlen=n)
        self.P_hist: Deque[float] = deque(maxlen=n)
        self.Pe_hist: Deque[float] = deque(maxlen=n)
        self.Tf_hist: Deque[float] = deque(maxlen=n)
        self.Tm_hist: Deque[float] = deque(maxlen=n)
        self.p_hist: Deque[float] = deque(maxlen=n)

        self._timer = None

        # Initialize to nominal steady state.
        self._reset_to_steady(clear_history=True)

    # ---------------------------------------------------------------------
    # Console / status helpers
    # ---------------------------------------------------------------------

    def _event(self, key: str, msg: str, min_interval_s: float = 0.25) -> None:
        """
        Print a throttled event message to the console.

        Parameters
        ----------
        key : str
            Event category key used for per-event throttling.
        msg : str
            Message to print.
        min_interval_s : float, default 0.25
            Minimum wall-clock interval between repeated messages for the same
            key.

        Notes
        -----
        This method is primarily for test-mode console feedback. A future GUI
        could instead route these events into a status panel or log widget.
        """
        now = time.time() - self._paused_wall_time
        last = self._last_event.get(key, 0.0)
        if now - last >= min_interval_s:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}")
            self._last_event[key] = now

    def _flags(self) -> list[str]:
        """
        Return the current simulator flag set as a list of strings.
        """
        flags: list[str] = []
        if self.ctrl.paused:
            flags.append("PAUSED")
        if self.x.stepback_active:
            flags.append("STEPBACK")
        if self.x.sds1_active:
            flags.append("SDS1")
        if self.x.sds2_active:
            flags.append("SDS2")
        if self.x.exploded:
            flags.append("EXPLODED")
        if not flags:
            flags.append("NORMAL")
        return flags

    def _print_key_state(self, header: str = "STATE") -> None:
        """
        Print a concise human-readable state summary.

        Intended for operators / developers who want a quick status snapshot.
        """
        Pe = self.p.eta_electric * self.x.P * self.p.Q_th_full_MW
        print(
            f"\n--- {header} ---\n"
            f"sim={time.time()-self._t0_wall:6.1f}s reactor={fmt_reactor_time(self._t_reactor)} speed={self.ctrl.time_scale:5.1f}x\n"
            f"P={fmt_pct(self.x.P)} Tf={self.x.Tf:6.1f}C Tm={self.x.Tm:5.1f}C Pe={Pe:7.1f}MW p={self.x.p_turb:4.2f}MPa\n"
            f"LZC={self.ctrl.lzc_fill_pct:5.1f}% ADJ={self.ctrl.adj_out_frac:4.2f} MCA={self.ctrl.mca_in_frac:4.2f} REFUEL={self.ctrl.refuel_rate_cmd:4.4f} GOAL={self.ctrl.goal_frac:4.2f}\n"
            f"I={self.x.I_hat:4.3f} Xe={self.x.Xe_hat:4.3f} rho_fuel={self.x.rho_fuel_mk:7.4f}mk flags={'|'.join(self._flags())}\n"
        )

    def _print_full_state(self, header: str = "STATE") -> None:
        """
        Print a detailed internal state summary.

        Useful for debugging, model verification, or future GUI diagnostics.
        """
        Pe = self.p.eta_electric * self.x.P * self.p.Q_th_full_MW
        print(
            f"\n--- {header} ---\n"
            f"P={self.x.P:.6f} C={self.x.C:.6f} I={self.x.I_hat:.6f} Xe={self.x.Xe_hat:.6f}\n"
            f"Tf={self.x.Tf:.3f} Tm={self.x.Tm:.3f} p={self.x.p_turb:.3f}\n"
            f"rho_fuel={self.x.rho_fuel_mk:.6f} rho_xe={self._rho_xe_mk():.6f} rho_fb={self._rho_feedback_mk():.6f}\n"
            f"LZC={self.ctrl.lzc_fill_pct:.3f} ADJ={self.ctrl.adj_out_frac:.6f} MCA={self.ctrl.mca_in_frac:.6f} REFUEL={self.ctrl.refuel_rate_cmd:.6f} GOAL={self.ctrl.goal_frac:.6f}\n"
            f"Pe={Pe:.2f} flags={'|'.join(self._flags())}\n"
        )

    # ---------------------------------------------------------------------
    # Reset / initialization
    # ---------------------------------------------------------------------

    def _reset_to_steady(self, clear_history: bool) -> None:
        """
        Reset the simulator to the nominal startup condition.

        Parameters
        ----------
        clear_history : bool
            If True, clear all stored history traces and seed them with a few
            initial samples.

        Notes
        -----
        This reset intentionally:
            - clears trips and warnings,
            - restores safety logic,
            - sets power to full power (P = 1),
            - sets xenon to a neutral starting value,
            - resets elapsed wall and reactor time.

        For a future GUI, this method is the main "reset plant" hook.
        """
        self._t0_wall = time.time()
        self._pause_start = None
        self._paused_wall_time = 0.0
        self._t_reactor = 0.0

        # Restore operator / command defaults.
        self.ctrl.safety_enabled = True
        self.ctrl.paused = False
        self.ctrl.time_scale = 1.0
        self.ctrl.goal_frac = 1.0
        self.ctrl.lzc_fill_pct = 50.0
        self.ctrl.adj_out_frac = 0.0
        self.ctrl.mca_in_frac = 0.0
        self.ctrl.refuel_rate_cmd = 0.9960
        self.ctrl.trip_sds1 = False
        self.ctrl.trip_sds2 = False
        self.ctrl.request_reset_steady = False
        self.ctrl.request_reset_sds = False
        self.ctrl.event_status.clear()

        # Restore reactor-state defaults.
        self.x.P = 1.0
        self.x.C = (self.p.beta_eff / (self.p.lambda_d_s * self.p.Lambda_s)) * self.x.P
        self.x.I_hat = 1.0
        self.x.Xe_hat = 1.0  # neutral startup xenon; will build toward Xe_eq > 1
        self.x.rho_fuel_mk = 0.0
        self.x.Tf = self.p.Tf0_C
        self.x.Tm = self.p.Tm0_C
        self.x.p_turb = self.p.p_base_MPa
        self.x.stepback_active = False
        self.x.sds1_active = False
        self.x.sds2_active = False
        self.x.exploded = False

        # Reset derived runtime state.
        self._prev_P = self.x.P
        self._lograte = 0.0
        self._warning_text = ""
        self._status_label = "STATUS: GOOD"

        if clear_history:
            self.t_wall_hist.clear()
            self.P_hist.clear()
            self.Pe_hist.clear()
            self.Tf_hist.clear()
            self.Tm_hist.clear()
            self.p_hist.clear()

            # Seed the history so plots / GUI traces have something to draw
            # immediately.
            for _ in range(5):
                self._push_history(time.time() - self._t0_wall - self._paused_wall_time)

    def _push_history(self, t_wall: float) -> None:
        """
        Append the current state to all plotting / display history buffers.

        Parameters
        ----------
        t_wall : float
            Wall-clock time since start [s], adjusted for paused duration.
        """
        self.t_wall_hist.append(t_wall)
        self.P_hist.append(self.x.P)
        self.Pe_hist.append(self.p.eta_electric * self.x.P * self.p.Q_th_full_MW)
        self.Tf_hist.append(self.x.Tf)
        self.Tm_hist.append(self.x.Tm)
        self.p_hist.append(self.x.p_turb)

    # ---------------------------------------------------------------------
    # Reactivity contributions
    # ---------------------------------------------------------------------

    def _rho_lzc_mk(self) -> float:
        """
        Liquid-zone control reactivity [mk].

        Model:
            rho_LZC = (w_lzc_total_mk / 100) * (50 - lzc_fill_pct)

        So:
            50% is neutral,
            lower fill -> positive reactivity,
            higher fill -> negative reactivity.
        """
        return (self.p.w_lzc_total_mk / 100.0) * (50.0 - self.ctrl.lzc_fill_pct)

    def _rho_adj_mk(self) -> float:
        """
        Adjuster reactivity [mk].

        Linearized model:
            rho_ADJ = w_adj_total_mk * adj_out_frac
        """
        return self.p.w_adj_total_mk * clamp(self.ctrl.adj_out_frac, 0.0, 1.0)

    def _rho_mca_mk(self) -> float:
        """
        Mechanical control absorber reactivity [mk].

        Linearized model:
            rho_MCA = w_mca_total_mk * mca_in_frac

        Since w_mca_total_mk is negative, insertion adds negative reactivity.
        """
        return self.p.w_mca_total_mk * clamp(self.ctrl.mca_in_frac, 0.0, 1.0)

    def _rho_feedback_mk(self) -> float:
        """
        Thermal feedback reactivity [mk].

        Equation:
            rho_fb = alpha_ftc * (Tf - Tf0) + alpha_mtc * (Tm - Tm0)
        """
        return (
            self.p.alpha_ftc_mk_per_C * (self.x.Tf - self.p.Tf0_C)
            + self.p.alpha_mtc_mk_per_C * (self.x.Tm - self.p.Tm0_C)
        )

    def _rho_xe_mk(self) -> float:
        """
        Xenon reactivity contribution [mk].

        Equation:
            rho_Xe = -w_xe_mk * (Xe_hat - 1)
        """
        return -self.p.w_xe_mk * (self.x.Xe_hat - 1.0)

    def _rho_shutdown_mk(self) -> float:
        """
        Shutdown / protection reactivity contribution [mk].

        Priority order:
            SDS2 > SDS1 > Stepback > 0
        """
        if self.x.sds2_active or self.ctrl.trip_sds2:
            return self.p.rho_sds2_mk
        if self.x.sds1_active or self.ctrl.trip_sds1:
            return self.p.rho_sds1_mk
        if self.x.stepback_active:
            return self.p.rho_stepback_mk
        return 0.0

    def _rho_total_dk(self) -> float:
        """
        Total reactivity [delta-k/k].

        Equation:
            rho_total = rho_fuel
                      + rho_LZC
                      + rho_ADJ
                      + rho_MCA
                      + rho_feedback
                      + rho_Xe
                      + rho_shutdown

        The sum is first formed in mk, then clamped, then converted to delta-k/k.
        """
        rho_mk = (
            self.x.rho_fuel_mk
            + self._rho_lzc_mk()
            + self._rho_adj_mk()
            + self._rho_mca_mk()
            + self._rho_feedback_mk()
            + self._rho_xe_mk()
            + self._rho_shutdown_mk()
        )

        # Clamp extreme values to keep the educational simulator numerically
        # well-behaved.
        return mk_to_dk(clamp(rho_mk, -1000.0, 30.0))

    # ---------------------------------------------------------------------
    # Physics update blocks
    # ---------------------------------------------------------------------

    def _update_kinetics_exact(self, rho: float, dt: float) -> None:
        """
        Advance the 1-group point-kinetics model exactly over dt.

        Parameters
        ----------
        rho : float
            Total reactivity [delta-k/k].
        dt : float
            Reactor-time substep [s].

        State model:
            d/dt [P] = [ (rho - beta_eff)/Lambda   lambda_d ] [P]
                 [C]   [ beta_eff/Lambda          -lambda_d] [C]
        """
        a11 = (rho - self.p.beta_eff) / self.p.Lambda_s
        a12 = self.p.lambda_d_s
        a21 = self.p.beta_eff / self.p.Lambda_s
        a22 = -self.p.lambda_d_s

        A = np.array([[a11, a12], [a21, a22]], dtype=float)
        E = expm2x2(A * dt)

        y2 = E @ np.array([self.x.P, self.x.C], dtype=float)
        self.x.P = float(max(y2[0], 0.0))
        self.x.C = float(max(y2[1], 0.0))

    def _update_thermal_exact(self, dt: float) -> None:
        """
        Advance the simplified thermal model over dt.

        Parameters
        ----------
        dt : float
            Reactor-time substep [s].

        Approximate steady-state targets:
            dT_core   = dTcore_full_C * P
            Tcool_avg = Tin + 0.5 * dT_core
            Tf_ss     = Tcool_avg + dT_fc_full_C * P
            Tm_ss     = Tm0 + Tm_slope_C_per_P * (P - 1)

        Then:
            Tf <- exact first-order lag toward Tf_ss
            Tm <- exact first-order lag toward Tm_ss
        """
        P = self.x.P
        dT_core = self.p.dTcore_full_C * P
        Tcool_avg = self.p.Tin_C + 0.5 * dT_core
        Tf_ss = Tcool_avg + self.p.dT_fc_full_C * P
        Tm_ss = self.p.Tm0_C + self.p.Tm_slope_C_per_P * (P - 1.0)

        self.x.Tf = first_order_exact(self.x.Tf, Tf_ss, self.p.tau_f_s, dt)
        self.x.Tm = first_order_exact(self.x.Tm, Tm_ss, self.p.tau_m_s, dt)

    def _update_pressure_exact(self, dt: float) -> None:
        """
        Advance the pressure proxy over dt.

        Pressure equilibrium model:
            p_eq = p_min + (p_base - p_min) * clamp(P, 0, 1)

        The current pressure then moves toward p_eq with time constant tau_p_s.
        """
        P = clamp(self.x.P, 0.0, 1.0)
        p_eq = self.p.p_min_MPa + (self.p.p_base_MPa - self.p.p_min_MPa) * P
        self.x.p_turb = first_order_exact(self.x.p_turb, p_eq, self.p.tau_p_s, dt)

    def _update_xe_i_exact(self, dt: float) -> None:
        """
        Advance the normalized iodine / xenon model over dt.

        Parameters
        ----------
        dt : float
            Reactor-time substep [s].

        Model:
            I_hat  -> first-order follow of power
            Xe_eq  = 1 + xe_eq_gain * I_hat
            Xe_hat -> first-order follow of Xe_eq

        This captures the intended qualitative behaviour:
            - as power is held high, xenon slowly rises above 1,
            - rho_Xe becomes more negative,
            - power tends to drift down unless corrected.
        """
        P = clamp(self.x.P, 0.0, 2.0)

        # Iodine-like state follows power on a long time scale.
        self.x.I_hat = first_order_exact(self.x.I_hat, P, self.p.tau_I_s, dt)

        # Xenon equilibrium is deliberately set above 1 at power so xenon slowly
        # builds and introduces negative reactivity.
        Xe_eq = 1.0 + self.p.xe_eq_gain * self.x.I_hat
        self.x.Xe_hat = first_order_exact(self.x.Xe_hat, Xe_eq, self.p.tau_Xe_s, dt)

        # Clamp to reasonable educational ranges.
        self.x.I_hat = clamp(self.x.I_hat, 0.0, 2.5)
        self.x.Xe_hat = clamp(self.x.Xe_hat, 0.0, 3.0)

    def _update_fuel_inventory(self, dt: float) -> None:
        """
        Advance the slow fuel / refuelling reactivity inventory over dt.

        Equation:
            d(rho_fuel_mk)/dt = burn_rate_full_mk_per_s * (refuel_rate_cmd - P)

        Interpretation:
            refuel_rate_cmd > P  -> positive long-term drift
            refuel_rate_cmd < P  -> negative long-term drift
        """
        drho = self.p.burn_rate_full_mk_per_s * (self.ctrl.refuel_rate_cmd - self.x.P)
        self.x.rho_fuel_mk += drho * dt
        self.x.rho_fuel_mk = clamp(
            self.x.rho_fuel_mk,
            -self.p.rho_fuel_limit_mk,
            self.p.rho_fuel_limit_mk,
        )

    def _compute_lograte(self, P: float, prev_P: float, dt: float) -> float:
        """
        Compute logarithmic power rate:

            d(ln P)/dt ≈ [ln(P_k) - ln(P_{k-1})] / dt

        Parameters
        ----------
        P : float
            Current power [-].
        prev_P : float
            Previous power [-].
        dt : float
            Reactor-time step [s].

        Returns
        -------
        float
            Logarithmic power rate [1/s].
        """
        if P < 0.02 or prev_P < 0.02:
            return 0.0
        return float((np.log(max(P, 1e-12)) - np.log(max(prev_P, 1e-12))) / max(dt, 1e-9))

    # ---------------------------------------------------------------------
    # Protection / warning logic
    # ---------------------------------------------------------------------

    def _apply_protection(self, lograte: float) -> None:
        """
        Evaluate and latch automatic protection actions.

        Parameters
        ----------
        lograte : float
            Current logarithmic power rate [1/s].

        Protection order
        ----------------
        1) SDS2
        2) SDS1
        3) Stepback

        Once latched, the corresponding reactivity is injected through
        _rho_shutdown_mk().
        """
        if not self.ctrl.safety_enabled:
            return

        P = self.x.P
        Tf = self.x.Tf

        # Highest-priority shutdown system.
        if (
            (lograte >= self.p.sds2_lograte_s)
            or (P >= self.p.rop_sds2_FP)
            or (Tf >= self.p.Tf_sds2_C)
            or self.ctrl.trip_sds2
        ):
            if not self.x.sds2_active:
                self.x.sds2_active = True
                msg = f"SDS2 ACTIVATED: log-rate={lograte:.3f} 1/s, P={fmt_pct(P)}, Tf={Tf:.1f} C"
                self._event("SDS2", msg)
                self.ctrl.event_status.append(msg)
            return

        # Lower-priority shutdown system.
        if (
            (lograte >= self.p.sds1_lograte_s)
            or (P >= self.p.rop_sds1_FP)
            or (Tf >= self.p.Tf_sds1_C)
            or self.ctrl.trip_sds1
        ):
            if not self.x.sds1_active:
                self.x.sds1_active = True
                msg = f"SDS1 ACTIVATED: log-rate={lograte:.3f} 1/s, P={fmt_pct(P)}, Tf={Tf:.1f} C"
                self._event("SDS1", msg)
                self.ctrl.event_status.append(msg)
            return

        # Stepback is a non-trip rapid setback.
        if (lograte >= self.p.stepback_lograte_s) and (not self.x.stepback_active):
            self.x.stepback_active = True
            msg = f"STEPBACK ACTIVATED: log-rate={lograte:.3f} 1/s, P={fmt_pct(P)}"
            self._event("STEPBACK", msg)
            self.ctrl.event_status.append("STEPBACK ACTIVATED")

    def _update_status_and_warning(self) -> None:
        """
        Update human-readable simulator status text.

        Status categories
        -----------------
        STATUS: GOOD
            Normal operating state

        STATUS: WARNING
            Margins are being approached

        STATUS: RESET REQUIRED
            SDS trip or simulated meltdown occurred
        """
        warning = ""
        status = "STATUS: GOOD"

        if self.x.sds1_active or self.x.sds2_active:
            status = "STATUS: RESET REQUIRED"
            if self.x.sds2_active:
                warning = "SDS2 TRIPPED: reset required after safe shutdown."
            else:
                warning = "SDS1 TRIPPED: reset required after safe shutdown."

        elif self.x.exploded:
            status = "STATUS: RESET REQUIRED"
            warning = "EXPLODED: use 'reset steady' to recover."

        elif not self.ctrl.safety_enabled:
            if (self.x.Tf >= 0.9 * self.p.Tf_explode_C) or (self.x.P >= 0.9 * self.p.P_explode_FP):
                status = "STATUS: WARNING"
                warning = "DANGER: close to explosion. Insert MCA / lower ADJ / increase LZC."

        else:
            if (
                (self.x.Tf >= self.p.Tf_warn_C)
                or (self.x.P >= 0.95 * self.p.rop_sds1_FP)
                or (self._lograte >= 0.8 * self.p.stepback_lograte_s)
            ):
                status = "STATUS: WARNING"
                warning = "WARNING: close to trip limits. Insert MCA / reduce ADJ / raise LZC."
                self.ctrl.event_status.append(warning)

        if warning and warning != self._warning_text:
            self._event("WARN", warning, min_interval_s=0.0)

        self._warning_text = warning
        self._status_label = status

    def _danger_if_no_safety(self) -> None:
        """
        Apply the educational 'meltdown' logic when safety is disabled.

        This is not intended as a plant-accurate accident progression model. It
        exists to support the capstone game's unsafe-mode behaviour.
        """
        if self.ctrl.safety_enabled or self.x.exploded:
            return

        if (self.x.Tf >= self.p.Tf_explode_C) or (self.x.P >= self.p.P_explode_FP):
            self.x.exploded = True
            self.x.P = max(self.x.P, self.p.P_explode_FP)
            self.x.Tf = max(self.x.Tf, self.p.Tf_explode_C)
            self._warning_text = "EXPLODED: use 'reset steady' to recover."
            self._status_label = "STATUS: RESET REQUIRED"

            msg = f"🔥 CORE GOT TOO HOT! Tf={self.x.Tf:.0f}C, P={fmt_pct(self.x.P)}. Reactor exploded (in sim)."
            self._event("BOOM", msg, min_interval_s=0.0)
            self.ctrl.event_status.append(
                f"🔥 CORE GOT TOO HOT! Temperature reached {self.x.Tf:.0f}C, Reactor Meltdown."
            )

    # ---------------------------------------------------------------------
    # Main physics step
    # ---------------------------------------------------------------------

    def step(self) -> None:
        """
        Advance the simulator by one wall-clock frame.

        Main sequence
        -------------
        1) Handle reset requests
        2) Handle paused / exploded modes
        3) Convert wall-clock dt to reactor-time dt
        4) Substep the physics if needed
        5) Update status / warnings
        6) Push current state into history buffers
        """
        # Full reset request.
        if self.ctrl.request_reset_steady:
            self._event("RESET", "RESET: steady state.", min_interval_s=0.0)
            self._reset_to_steady(True)
            self._print_key_state("RESET STEADY")
            return

        # Shutdown-latch clear request.
        if self.ctrl.request_reset_sds:
            if self.x.P < 0.01:
                self.x.stepback_active = False
                self.x.sds1_active = False
                self.x.sds2_active = False
                self.ctrl.trip_sds1 = False
                self.ctrl.trip_sds2 = False
                self._event("RESET_SDS", "RESET: SDS latches cleared.", min_interval_s=0.0)
            else:
                self._event("RESET_SDS_DENY", "RESET DENIED: reduce P below 1% FP first.", min_interval_s=0.0)
                self.ctrl.event_status.append("RESET DENIED: Reduce P below 1% FP first.")
            self.ctrl.request_reset_sds = False

        # If paused, do not advance reactor time or state, but keep history alive.
        if self.ctrl.paused:
            self._push_history(time.time() - self._t0_wall - self._paused_wall_time)
            return

        # If already in exploded state, freeze physics until user resets.
        if self.x.exploded:
            self._push_history(time.time() - self._t0_wall - self._paused_wall_time)
            return

        # Convert the wall-clock update interval to reactor-time.
        dt_reactor = self.p.dt_wall_s * self.ctrl.time_scale

        # Split large accelerated steps into smaller reactor-time substeps to
        # preserve stable / responsive behaviour.
        n_sub = max(1, int(np.ceil(dt_reactor / self.p.dt_max_reactor_s)))
        dt = dt_reactor / n_sub

        for _ in range(n_sub):
            # Compute current logarithmic power rate and evaluate protection.
            lograte = self._compute_lograte(self.x.P, self._prev_P, dt)
            self._lograte = lograte
            self._apply_protection(lograte)

            # Total reactivity from all contributing mechanisms.
            rho = self._rho_total_dk()

            # Advance all physics blocks.
            self._prev_P = self.x.P
            self._update_kinetics_exact(rho, dt)
            self._update_xe_i_exact(dt)
            self._update_fuel_inventory(dt)
            self._update_thermal_exact(dt)
            self._update_pressure_exact(dt)

            # Safety-off meltdown logic.
            self._danger_if_no_safety()
            if self.x.exploded:
                break

        self._t_reactor += dt_reactor
        self._update_status_and_warning()
        self._push_history(time.time() - self._t0_wall - self._paused_wall_time)

    # ---------------------------------------------------------------------
    # Runtime entry points
    # ---------------------------------------------------------------------

    def run(self) -> None:
        """
        Start the simulator threads.

        Current behaviour
        -----------------
        This method:
            - starts the physics loop thread,
            - starts the console-input thread,
            - prints initial status.

        It does NOT automatically call _plot() in this final version.

        Notes
        ----------------
        This supports PyQt6 integration: the simulator engine can
        run independently while a future GUI owns the plotting and controls.

        For console-only / Matplotlib testing, we can call:
            sim._plot()
        after run(), or modify run() to launch _plot().
        """
        self._event("VERSION", "Running candu_realtime_sim_v11b_gui.py", min_interval_s=0.0)
        self._event(
            "START",
            f"Started near steady state (P={fmt_pct(self.x.P)}). Goal={self.ctrl.goal_frac:.2f} FP. Type 'help'.",
            min_interval_s=0.0,
        )
        self._print_key_state("INITIAL")

        threading.Thread(target=self._physics_loop, daemon=True).start()
        threading.Thread(target=self._console_loop, daemon=True).start()

    def _physics_loop(self) -> None:
        """
        Background loop that advances the simulation at fixed wall-clock cadence.

        Notes
        -----
        - The loop aims for dt_wall_s spacing.
        - While paused, it freezes the schedule and sleeps lightly.
        - The actual physics advancement happens inside step().
        """
        next_tick = time.time()

        while self._running:
            if self.ctrl.paused:
                # Freeze the schedule while paused so the physics loop does not
                # try to "catch up" when resumed.
                next_tick = time.time()
                time.sleep(0.01)
                continue

            now = time.time()
            if now < next_tick:
                time.sleep(max(0.001, next_tick - now))
                continue

            with self._lock:
                self.step()

            next_tick += self.p.dt_wall_s

    def _console_loop(self) -> None:
        """
        Background loop for console command input.

        This is primarily for development and testing. A GUI front end would
        likely replace this with direct button / slider callbacks.
        """
        print("\n> ", end="", flush=True)

        while self._running:
            try:
                cmd = input().strip()
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

            if cmd:
                with self._lock:
                    self._handle_command(cmd)

            print("> ", end="", flush=True)

    def _plot(self) -> None:
        """
        Launch the built-in Matplotlib plot window.

        Intended use
        ------------
        This is a developer convenience function for quick testing. In the final
        GUI architecture, the future PyQt6 front end will likely replace this
        with its own plot widgets.

        Plot panels
        -----------
        Top-left:
            Neutron power [%FP]

        Top-right:
            Temperatures [°C]

        Bottom-left:
            Electric power [MW]

        Bottom-right:
            Steam-generator / turbine pressure [MPa]
        """
        fig, axs = plt.subplots(2, 2, figsize=(12, 7.5))
        fig.canvas.manager.set_window_title("CANDU Real-Time Simulator v11b (documented)")

        axP, axT, axE, axS = axs[0, 0], axs[0, 1], axs[1, 0], axs[1, 1]

        (lineP,) = axP.plot([], [], linewidth=2)
        (lineTf,) = axT.plot([], [], linewidth=2, label="Tf")
        (lineTm,) = axT.plot([], [], linewidth=2, label="Tm")
        (lineE,) = axE.plot([], [], linewidth=2)
        (lineEgoal,) = axE.plot([], [], linewidth=1, linestyle="--")
        (lineS,) = axS.plot([], [], linewidth=2)

        axP.set_title("Neutron power")
        axP.set_xlabel("Sim time [s]")
        axP.set_ylabel("Power [%FP]")
        axP.grid(True)

        axT.set_title("Temperatures")
        axT.set_xlabel("Sim time [s]")
        axT.set_ylabel("Temperature [°C]")
        axT.grid(True)
        axT.legend(loc="best")

        axE.set_title("Electric power (scaled)")
        axE.set_xlabel("Sim time [s]")
        axE.set_ylabel("P_e [MW]")
        axE.grid(True)

        axS.set_title("Steam-generator / turbine pressure")
        axS.set_xlabel("Sim time [s]")
        axS.set_ylabel("Pressure [MPa]")
        axS.grid(True)

        status_txt = fig.text(0.01, 0.01, "", fontsize=9, family="monospace")
        state_txt = fig.text(0.52, 0.01, "", fontsize=10, color="red", family="sans-serif")

        def redraw():
            """Timer callback that refreshes all plot traces from history buffers."""
            if not self._running:
                return

            with self._lock:
                t = np.asarray(self.t_wall_hist)
                P = np.asarray(self.P_hist)
                Tf = np.asarray(self.Tf_hist)
                Tm = np.asarray(self.Tm_hist)
                Pe = np.asarray(self.Pe_hist)
                pp = np.asarray(self.p_hist)
                Pe_goal = self.p.eta_electric * (self.ctrl.goal_frac * self.p.Q_th_full_MW)

                status_txt.set_text(
                    f"sim={t[-1]:6.1f}s reactor={fmt_reactor_time(self._t_reactor)} speed={self.ctrl.time_scale:5.1f}x\n"
                    f"P={fmt_pct(self.x.P)} Tf={self.x.Tf:6.1f}C Tm={self.x.Tm:5.1f}C I={self.x.I_hat:4.3f} Xe={self.x.Xe_hat:4.3f} fuel={self.x.rho_fuel_mk:7.4f}mk\n"
                    f"LZC={self.ctrl.lzc_fill_pct:5.1f}% ADJ={self.ctrl.adj_out_frac:4.2f} MCA={self.ctrl.mca_in_frac:4.2f} REFUEL={self.ctrl.refuel_rate_cmd:4.4f} GOAL={self.ctrl.goal_frac:4.2f} flags={'|'.join(self._flags())}"
                )

                if self._warning_text:
                    state_txt.set_text(f"{self._status_label} | {self._warning_text}")
                else:
                    state_txt.set_text(self._status_label)

            if t.size < 2:
                fig.canvas.draw_idle()
                return

            lineP.set_data(t, 100.0 * P)
            lineTf.set_data(t, Tf)
            lineTm.set_data(t, Tm)
            lineE.set_data(t, Pe)
            lineS.set_data(t, pp)
            lineEgoal.set_data([t[0], t[-1]], [Pe_goal, Pe_goal])

            xmin = max(0.0, t[-1] - self.p.history_wall_s)
            xmax = t[-1]

            for ax in (axP, axT, axE, axS):
                ax.set_xlim(xmin, xmax)

            Pmax = float(np.nanmax(P)) if np.isfinite(P).any() else 1.0
            axP.set_ylim(0, max(140, 100 * Pmax + 10))

            Tfmax = float(np.nanmax(Tf)) if np.isfinite(Tf).any() else self.p.Tf0_C
            Tmin = float(np.nanmin(Tm)) if np.isfinite(Tm).any() else self.p.Tm0_C
            axT.set_ylim(min(Tmin - 10, 0), max(Tfmax + 50, 900))

            Pemax = float(np.nanmax(Pe)) if np.isfinite(Pe).any() else self.p.eta_electric * self.p.Q_th_full_MW
            axE.set_ylim(0, max(Pe_goal + 200, Pemax + 50))

            axS.set_ylim(0.0, 5.2)
            fig.canvas.draw_idle()

        self._timer = fig.canvas.new_timer(interval=int(1000 * self.p.dt_wall_s))
        self._timer.add_callback(redraw)
        self._timer.start()
        plt.show()

    # ---------------------------------------------------------------------
    # Command parser
    # ---------------------------------------------------------------------

    def _handle_command(self, cmd: str) -> None:
        """
        Parse and apply a single console command string.

        Supported forms
        ---------------
        help
        status
        pause sim
        resume sim
        set safety on|off
        set speed <1..3000>
        set goal <0..1.2>
        set lzc <0..100>
        set adj <0..1>
        set mca <0..1>
        set refuel <0..2.0>
        trip sds1
        trip sds2
        reset sds
        reset steady
        quit

        Notes
        -----
        The alias "refeul" was added since the developer, Sarah_K 
        kept typing the wrong spelling on the console while testing
        """
        parts = cmd.split()
        if not parts:
            return

        c0 = parts[0].lower()

        if c0 in ("help", "?"):
            print(
                "Commands:\n"
                "  help\n  status\n  pause sim\n  resume sim\n"
                "  set safety on|off\n  set speed <1..3000>\n  set goal <0..1.2>\n"
                "  set lzc <0..100>\n  set adj <0..1>\n  set mca <0..1>\n  set refuel <0..2.0>\n"
                "  trip sds1|sds2\n  reset sds\n  reset steady\n  quit\n"
            )
            return

        if c0 == "status":
            self._print_full_state("STATUS")
            return

        if c0 == "pause" and len(parts) == 2 and parts[1].lower() == "sim":
            self.ctrl.paused = True
            self._pause_start = time.time()
            self._event("PAUSE", "Simulation paused.", min_interval_s=0.0)
            self._print_key_state("PAUSE")
            return

        if c0 == "resume" and len(parts) == 2 and parts[1].lower() == "sim":
            self.ctrl.paused = False
            if self._pause_start is not None:
                self._paused_wall_time += time.time() - self._pause_start
                self._pause_start = None
            self._event("RESUME", "Simulation resumed.", min_interval_s=0.0)
            self._print_key_state("RESUME")
            return

        if c0 in ("quit", "exit"):
            self._event("QUIT", "Stopping simulator ...", min_interval_s=0.0)
            self._running = False
            return

        if c0 == "set" and len(parts) >= 3:
            what = parts[1].lower()
            val = parts[2].lower()

            if what == "safety":
                if val in ("on", "off"):
                    self.ctrl.safety_enabled = (val == "on")
                    self._event("SET", f"Safety -> {'ON' if self.ctrl.safety_enabled else 'OFF'}", min_interval_s=0.0)
                    self._print_key_state("PARAM CHANGE")
                else:
                    self._event("ERR", "safety must be on|off", min_interval_s=0.0)
                return

            try:
                fval = float(parts[2])
            except ValueError:
                self._event("ERR", "Value must be numeric.", min_interval_s=0.0)
                return

            if what == "speed":
                self.ctrl.time_scale = clamp(fval, 1.0, self.p.max_speed)
                self._event("SET", f"Speed -> {self.ctrl.time_scale:.1f}x", min_interval_s=0.0)

            elif what == "goal":
                self.ctrl.goal_frac = clamp(fval, 0.0, 1.2)
                self._event("SET", f"Goal -> {self.ctrl.goal_frac:.2f} FP", min_interval_s=0.0)

            elif what == "lzc":
                self.ctrl.lzc_fill_pct = clamp(fval, 0.0, 100.0)
                self._event("SET", f"LZC -> {self.ctrl.lzc_fill_pct:.1f}%", min_interval_s=0.0)

            elif what == "adj":
                self.ctrl.adj_out_frac = clamp(fval, 0.0, 1.0)
                self._event("SET", f"ADJ -> {self.ctrl.adj_out_frac:.2f}", min_interval_s=0.0)

            elif what == "mca":
                self.ctrl.mca_in_frac = clamp(fval, 0.0, 1.0)
                self._event("SET", f"MCA -> {self.ctrl.mca_in_frac:.2f}", min_interval_s=0.0)

            elif what in ("refuel", "refeul"):
                self.ctrl.refuel_rate_cmd = clamp(fval, 0.0, 2.0)
                self._event("SET", f"REFUEL -> {self.ctrl.refuel_rate_cmd:.4f}", min_interval_s=0.0)

            else:
                self._event("ERR", "Unknown set target.", min_interval_s=0.0)
                return

            self._print_key_state("PARAM CHANGE")
            return

        if c0 == "trip" and len(parts) == 2:
            t = parts[1].lower()

            if t == "sds1":
                self.ctrl.trip_sds1 = True
                self._event("TRIP", "Manual TRIP: SDS1 requested", min_interval_s=0.0)
                self._print_key_state("PARAM CHANGE")
                return

            if t == "sds2":
                self.ctrl.trip_sds2 = True
                self._event("TRIP", "Manual TRIP: SDS2 requested", min_interval_s=0.0)
                self._print_key_state("PARAM CHANGE")
                return

            self._event("ERR", "Usage: trip sds1|sds2", min_interval_s=0.0)
            return

        if c0 == "reset" and len(parts) == 2:
            r = parts[1].lower()

            if r == "steady":
                self.ctrl.request_reset_steady = True
                return

            if r == "sds":
                self.ctrl.request_reset_sds = True
                return

            self._event("ERR", "Usage: reset steady|sds", min_interval_s=0.0)
            return

        self._event("ERR", "Unknown command. Type help.", min_interval_s=0.0)


def main() -> None:
    """
    Console entry point.

    Creates one simulator instance and starts the background threads.
    """
    sim = CanduRealtimeSim(PlantParams())
    sim.run()


if __name__ == "__main__":
    main()
