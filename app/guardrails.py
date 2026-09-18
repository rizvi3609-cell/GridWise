"""
Deterministic Guardrail and Sanitizer layer for GridWise LLM.
Enforces Problem Statement Section 04 & Section 08 rules before optimization.
"""

from typing import Any, Dict, List, Optional
import math
from app.schemas import (
    BatteryInput,
    DirectiveInterpretation,
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
)


def sanitize_hours(raw_hours: Any) -> List[int]:
    """
    Validates, filters to 0..23, deduplicates, and sorts hours ascending.
    """
    if not isinstance(raw_hours, list):
        return []
    valid_hours = set()
    for h in raw_hours:
        try:
            h_int = int(h)
            if 0 <= h_int <= 23:
                valid_hours.add(h_int)
        except (ValueError, TypeError):
            continue
    return sorted(list(valid_hours))


def sanitize_directive(
    raw: Dict[str, Any],
    expected_index: int,
    battery: BatteryInput,
) -> DirectiveInterpretation:
    """
    Sanitizes a single raw directive dictionary from untrusted model output.
    """
    raw_type = str(raw.get("directive_type", "")).strip().lower()

    # Match against supported directive types
    matched_type: Optional[DirectiveType] = None
    for dt in DirectiveType:
        if raw_type == dt.value:
            matched_type = dt
            break

    # If unknown or invalid type, safely fallback to no_op
    if matched_type is None:
        matched_type = DirectiveType.NO_OP

    explanation = str(raw.get("explanation", "")).strip()
    if not explanation:
        explanation = f"Directive {matched_type.value} processed."

    # Handle no_op
    if matched_type == DirectiveType.NO_OP:
        return DirectiveInterpretation(
            note_index=expected_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation=explanation or "This note does not affect today's energy schedule.",
        )

    # Handle active directives
    adj = raw.get("structured_adjustment") or {}
    hours = sanitize_hours(adj.get("hours", []))

    # If hours is empty, this directive cannot apply validly -> downgrade to no_op
    if not hours:
        return DirectiveInterpretation(
            note_index=expected_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="Invalid time window specified; treated as no_op.",
        )

    if matched_type == DirectiveType.SOLAR_REDUCTION:
        try:
            factor = float(adj.get("factor", 1.0))
            if math.isnan(factor) or math.isinf(factor):
                factor = 1.0
            factor = max(0.0, min(1.0, factor))
        except (ValueError, TypeError):
            factor = 1.0

        return DirectiveInterpretation(
            note_index=expected_index,
            applies=True,
            directive_type=DirectiveType.SOLAR_REDUCTION,
            structured_adjustment=SolarReductionAdjustment(hours=hours, factor=factor),
            explanation=explanation,
        )

    elif matched_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
        try:
            reserve = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            if math.isnan(reserve) or math.isinf(reserve):
                reserve = battery.minimum_energy_kwh
            # Reserve cannot be negative or exceed battery capacity
            reserve = max(battery.minimum_energy_kwh, min(battery.capacity_kwh, reserve))
        except (ValueError, TypeError):
            reserve = battery.minimum_energy_kwh

        return DirectiveInterpretation(
            note_index=expected_index,
            applies=True,
            directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
            structured_adjustment=MinimumBatteryReserveAdjustment(
                hours=hours,
                minimum_energy_kwh=round(reserve, 4),
            ),
            explanation=explanation,
        )

    elif matched_type in (DirectiveType.NO_CHARGE_WINDOW, DirectiveType.NO_DISCHARGE_WINDOW):
        return DirectiveInterpretation(
            note_index=expected_index,
            applies=True,
            directive_type=matched_type,
            structured_adjustment=WindowAdjustment(hours=hours),
            explanation=explanation,
        )

    elif matched_type == DirectiveType.MAX_GRID_WINDOW:
        try:
            grid_cap = float(adj.get("max_grid_kwh", 0.0))
            if math.isnan(grid_cap) or math.isinf(grid_cap):
                grid_cap = 0.0
            grid_cap = max(0.0, grid_cap)
        except (ValueError, TypeError):
            grid_cap = 0.0

        return DirectiveInterpretation(
            note_index=expected_index,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment=MaxGridAdjustment(
                hours=hours,
                max_grid_kwh=round(grid_cap, 4),
            ),
            explanation=explanation,
        )

    # Catch-all safe fallback
    return DirectiveInterpretation(
        note_index=expected_index,
        applies=False,
        directive_type=DirectiveType.NO_OP,
        structured_adjustment=None,
        explanation=explanation,
    )


def sanitize_all_directives(
    raw_directives: List[Dict[str, Any]],
    expected_count: int,
    battery: BatteryInput,
) -> List[DirectiveInterpretation]:
    """
    Ensures exactly expected_count directives in note_index order 0..N-1.
    """
    indexed_map: Dict[int, Dict[str, Any]] = {}
    for item in raw_directives:
        if isinstance(item, dict):
            idx = item.get("note_index")
            if isinstance(idx, int) and 0 <= idx < expected_count and idx not in indexed_map:
                indexed_map[idx] = item

    results: List[DirectiveInterpretation] = []
    for i in range(expected_count):
        raw_item = indexed_map.get(i, {"note_index": i, "directive_type": "no_op"})
        clean_entry = sanitize_directive(raw_item, i, battery)
        results.append(clean_entry)

    return results
