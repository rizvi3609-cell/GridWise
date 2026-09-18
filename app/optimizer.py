"""
Mathematical Energy Scheduling Optimizer for GridWise LLM.
Formulates and solves a 24-hour Linear Program using scipy.optimize.linprog (method='highs').
"""

from typing import List, Tuple
import numpy as np
from scipy.optimize import linprog

from app.schemas import (
    BatteryAction,
    BatteryInput,
    DirectiveInterpretation,
    DirectiveType,
    HourInput,
    HourlyPlanEntry,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
)


def solve_energy_dispatch(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretation],
) -> Tuple[List[HourlyPlanEntry], float, float, float, str]:
    """
    Solves the 24-hour energy optimization problem using SciPy HiGHS LP solver.

    Returns:
        hourly_plan: List[HourlyPlanEntry] for hours 0..23
        total_grid_kwh: float
        total_cost_bdt: float
        peak_grid_kwh: float
        plan_summary: str
    """
    # 1. Initialize 24-hour parameter vectors
    solar_factors = [1.0] * 24
    min_reserves = [battery.minimum_energy_kwh] * 24
    charge_limits = [battery.max_charge_kwh_per_hour] * 24
    discharge_limits = [battery.max_discharge_kwh_per_hour] * 24
    grid_caps = [None] * 24

    # 2. Apply sanitized directives to parameters
    for d in directives:
        if not d.applies or not d.structured_adjustment:
            continue
        adj = d.structured_adjustment
        h_list = adj.hours

        if d.directive_type == DirectiveType.SOLAR_REDUCTION and isinstance(adj, SolarReductionAdjustment):
            for h in h_list:
                solar_factors[h] = min(solar_factors[h], adj.factor)

        elif d.directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE and isinstance(adj, MinimumBatteryReserveAdjustment):
            for h in h_list:
                min_reserves[h] = max(min_reserves[h], adj.minimum_energy_kwh)

        elif d.directive_type == DirectiveType.NO_CHARGE_WINDOW and isinstance(adj, WindowAdjustment):
            for h in h_list:
                charge_limits[h] = 0.0

        elif d.directive_type == DirectiveType.NO_DISCHARGE_WINDOW and isinstance(adj, WindowAdjustment):
            for h in h_list:
                discharge_limits[h] = 0.0

        elif d.directive_type == DirectiveType.MAX_GRID_WINDOW and isinstance(adj, MaxGridAdjustment):
            for h in h_list:
                if grid_caps[h] is None:
                    grid_caps[h] = adj.max_grid_kwh
                else:
                    grid_caps[h] = min(grid_caps[h], adj.max_grid_kwh)

    # 3. Decision variables (120 variables total):
    # g[0..23]   : indices 0..23
    # s[0..23]   : indices 24..47
    # c[0..23]   : indices 48..71
    # d[0..23]   : indices 72..95
    # E[0..23]   : indices 96..119
    n_vars = 120

    # Objective: Minimize sum(tariff[h] * g[h]) + eps * (c[h] + d[h])
    # Epsilon regularization prevents phantom cycling and enforces strict complementarity
    c_obj = np.zeros(n_vars)
    for h in range(24):
        c_obj[h] = hours[h].tariff_bdt_per_kwh
        c_obj[48 + h] = 1e-6
        c_obj[72 + h] = 1e-6

    # Variable bounds
    bounds = []
    # g[h]
    for h in range(24):
        bounds.append((0.0, grid_caps[h]))
    # s[h]
    for h in range(24):
        eff_solar = max(0.0, hours[h].solar_kwh * solar_factors[h])
        bounds.append((0.0, eff_solar))
    # c[h]
    for h in range(24):
        bounds.append((0.0, charge_limits[h]))
    # d[h]
    for h in range(24):
        bounds.append((0.0, discharge_limits[h]))
    # E[h]
    for h in range(24):
        bounds.append((min_reserves[h], battery.capacity_kwh))

    # Equality constraints (49 equations):
    # 1. Energy balance: g[h] + s[h] - c[h] + d[h] = demand[h]  (24 equations)
    # 2. Battery state transitions:                              (24 equations)
    #      h=0: E[0] - c[0] + d[0] = E_initial
    #      h>0: E[h] - E[h-1] - c[h] + d[h] = 0
    # 3. End of day neutrality: E[23] = E_initial               (1 equation)
    A_eq = []
    b_eq = []

    for h in range(24):
        row = np.zeros(n_vars)
        row[h] = 1.0       # g[h]
        row[24 + h] = 1.0  # s[h]
        row[48 + h] = -1.0 # -c[h]
        row[72 + h] = 1.0  # d[h]
        A_eq.append(row)
        b_eq.append(hours[h].demand_kwh)

    # h = 0 battery update
    row = np.zeros(n_vars)
    row[96] = 1.0       # E[0]
    row[48] = -1.0      # -c[0]
    row[72] = 1.0       # d[0]
    A_eq.append(row)
    b_eq.append(battery.initial_energy_kwh)

    # h = 1..23 battery updates
    for h in range(1, 24):
        row = np.zeros(n_vars)
        row[96 + h] = 1.0      # E[h]
        row[96 + h - 1] = -1.0  # -E[h-1]
        row[48 + h] = -1.0     # -c[h]
        row[72 + h] = 1.0      # d[h]
        A_eq.append(row)
        b_eq.append(0.0)

    # End of day neutrality: E[23] = E_initial
    row = np.zeros(n_vars)
    row[96 + 23] = 1.0
    A_eq.append(row)
    b_eq.append(battery.initial_energy_kwh)

    res = linprog(
        c_obj,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs",
    )

    if not res.success:
        raise RuntimeError(f"LP optimization failed: {res.message}")

    # Extract optimal values
    g_raw = res.x[0:24]
    s_raw = res.x[24:48]
    c_raw = res.x[48:72]
    d_raw = res.x[72:96]
    e_raw = res.x[96:120]

    # Convert to strict schema and hourly plan entries
    plan_entries: List[HourlyPlanEntry] = []
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    threshold = 1e-4

    prev_e = battery.initial_energy_kwh

    for h in range(24):
        c_val = float(c_raw[h])
        d_val = float(d_raw[h])
        s_val = float(s_raw[h])
        dem = float(hours[h].demand_kwh)
        tariff = float(hours[h].tariff_bdt_per_kwh)

        # Discrete action classification
        if c_val > threshold and c_val >= d_val:
            action = BatteryAction.CHARGE
            batt_kwh = round(c_val, 4)
            d_val_effective = 0.0
            c_val_effective = batt_kwh
        elif d_val > threshold:
            action = BatteryAction.DISCHARGE
            batt_kwh = round(d_val, 4)
            c_val_effective = 0.0
            d_val_effective = batt_kwh
        else:
            action = BatteryAction.IDLE
            batt_kwh = 0.0
            c_val_effective = 0.0
            d_val_effective = 0.0

        # Effective solar used
        eff_solar = round(min(s_val, hours[h].solar_kwh * solar_factors[h]), 4)
        eff_solar = max(0.0, eff_solar)

        # Exact energy balance: g + s + d = dem + c => g = dem + c - s - d
        g_val = max(0.0, round(dem + c_val_effective - eff_solar - d_val_effective, 4))

        # Battery energy after hour
        e_after = round(prev_e + c_val_effective - d_val_effective, 4)
        # Numerical protection: clamp strictly to [min_reserves[h], capacity]
        e_after = max(min_reserves[h], min(battery.capacity_kwh, e_after))
        if h == 23:
            e_after = round(battery.initial_energy_kwh, 4)

        prev_e = e_after

        plan_entries.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=g_val,
                solar_used_kwh=eff_solar,
                battery_action=action,
                battery_kwh=batt_kwh,
                battery_energy_after_kwh=e_after,
            )
        )

        total_grid += g_val
        total_cost += g_val * tariff
        if g_val > peak_grid:
            peak_grid = g_val

    # Generate summary
    charge_hours = [p.hour for p in plan_entries if p.battery_action == BatteryAction.CHARGE]
    discharge_hours = [p.hour for p in plan_entries if p.battery_action == BatteryAction.DISCHARGE]
    summary = (
        f"Optimized schedule charging in {len(charge_hours)} hours and discharging in "
        f"{len(discharge_hours)} hours to minimize grid cost while respecting solar availability, "
        f"battery bounds, and operator directives."
    )

    return plan_entries, round(total_grid, 4), round(total_cost, 4), round(peak_grid, 4), summary
