"""
Independent Replay Verifier for GridWise LLM.
Validates the generated hourly plan against all physical and operational constraints
before the final API response is returned.
"""

from typing import List, Tuple
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


def verify_hourly_plan(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretation],
    plan: List[HourlyPlanEntry],
    reported_total_grid: float,
    reported_total_cost: float,
    reported_peak_grid: float,
    tolerance: float = 0.01,
) -> Tuple[bool, List[str]]:
    """
    Audits the generated schedule step-by-step.
    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if len(plan) != 24:
        errors.append(f"hourly_plan length is {len(plan)}, expected exactly 24")
        return False, errors

    # Directives compilation
    solar_factors = [1.0] * 24
    min_reserves = [battery.minimum_energy_kwh] * 24
    no_charge_hours = set()
    no_discharge_hours = set()
    grid_caps = {}

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
                no_charge_hours.add(h)
        elif d.directive_type == DirectiveType.NO_DISCHARGE_WINDOW and isinstance(adj, WindowAdjustment):
            for h in h_list:
                no_discharge_hours.add(h)
        elif d.directive_type == DirectiveType.MAX_GRID_WINDOW and isinstance(adj, MaxGridAdjustment):
            for h in h_list:
                grid_caps[h] = min(grid_caps.get(h, float("inf")), adj.max_grid_kwh)

    prev_energy = battery.initial_energy_kwh
    calc_grid = 0.0
    calc_cost = 0.0
    calc_peak = 0.0

    for h, entry in enumerate(plan):
        if entry.hour != h:
            errors.append(f"Hour mismatch at index {h}: got {entry.hour}")

        g = entry.grid_kwh
        s = entry.solar_used_kwh
        act = entry.battery_action
        b_kwh = entry.battery_kwh
        e_after = entry.battery_energy_after_kwh

        dem = hours[h].demand_kwh
        orig_s = hours[h].solar_kwh
        tariff = hours[h].tariff_bdt_per_kwh
        eff_solar = orig_s * solar_factors[h]

        c = b_kwh if act == BatteryAction.CHARGE else 0.0
        d = b_kwh if act == BatteryAction.DISCHARGE else 0.0

        # Non-negative checks
        if g < -tolerance or s < -tolerance or b_kwh < -tolerance or e_after < -tolerance:
            errors.append(f"Hour {h}: negative value detected")

        # Idle check
        if act == BatteryAction.IDLE and b_kwh > tolerance:
            errors.append(f"Hour {h}: action is idle but battery_kwh is {b_kwh}")

        # Solar bound check
        if s > eff_solar + tolerance:
            errors.append(f"Hour {h}: solar_used_kwh {s} > effective solar {eff_solar}")

        # Energy balance check
        supply = g + s + d
        demand_total = dem + c
        if abs(supply - demand_total) > tolerance:
            errors.append(f"Hour {h}: energy balance mismatch: {supply} != {demand_total}")

        # Battery dynamics check
        expected_e = prev_energy + c - d
        if abs(e_after - expected_e) > tolerance and h != 23:
            errors.append(f"Hour {h}: battery state mismatch: {e_after} != {expected_e}")

        # Reserve and capacity bounds
        if e_after < min_reserves[h] - tolerance:
            errors.append(f"Hour {h}: battery reserve violation: {e_after} < {min_reserves[h]}")
        if e_after > battery.capacity_kwh + tolerance:
            errors.append(f"Hour {h}: battery capacity violation: {e_after} > {battery.capacity_kwh}")

        # Rate limits
        if c > battery.max_charge_kwh_per_hour + tolerance:
            errors.append(f"Hour {h}: charge rate exceeded: {c} > {battery.max_charge_kwh_per_hour}")
        if d > battery.max_discharge_kwh_per_hour + tolerance:
            errors.append(f"Hour {h}: discharge rate exceeded: {d} > {battery.max_discharge_kwh_per_hour}")

        # Directives windows
        if c > tolerance and h in no_charge_hours:
            errors.append(f"Hour {h}: charging during no_charge_window")
        if d > tolerance and h in no_discharge_hours:
            errors.append(f"Hour {h}: discharging during no_discharge_window")
        if h in grid_caps and g > grid_caps[h] + tolerance:
            errors.append(f"Hour {h}: grid import {g} > cap {grid_caps[h]}")

        prev_energy = e_after
        calc_grid += g
        calc_cost += g * tariff
        calc_peak = max(calc_peak, g)

    # End of day neutrality
    if abs(prev_energy - battery.initial_energy_kwh) > tolerance:
        errors.append(f"End of day neutrality failure: {prev_energy} != {battery.initial_energy_kwh}")

    # Totals check
    if abs(calc_grid - reported_total_grid) > 0.1:
        errors.append(f"total_grid_kwh mismatch: {reported_total_grid} vs calculated {calc_grid}")
    if abs(calc_cost - reported_total_cost) > 0.1:
        errors.append(f"total_cost_bdt mismatch: {reported_total_cost} vs calculated {calc_cost}")
    if abs(calc_peak - reported_peak_grid) > 0.1:
        errors.append(f"peak_grid_kwh mismatch: {reported_peak_grid} vs calculated {calc_peak}")

    return len(errors) == 0, errors
