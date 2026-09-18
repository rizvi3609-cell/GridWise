"""
Pydantic schemas strictly matching the BUP CSE FEST 2026 GridWise LLM API contract.
"""

from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


# --- Request Models ---

class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0..23)")
    demand_kwh: float = Field(..., ge=0.0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0.0, description="Base solar generation forecast in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0.0, description="Grid electricity tariff in BDT/kWh")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0.0, description="Maximum battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0.0, description="Initial battery energy in kWh")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Base minimum reserve level in kWh")
    max_charge_kwh_per_hour: float = Field(..., ge=0.0, description="Max charge rate in kWh/hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0.0, description="Max discharge rate in kWh/hour")

    @model_validator(mode="after")
    def validate_battery_levels(self):
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        return self


class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural language notes")
    hours: List[HourInput] = Field(..., description="Array of exactly 24 hourly entries")
    battery: BatteryInput = Field(..., description="Battery parameters")

    @field_validator("hours")
    def validate_hours_length_and_order(cls, v: List[HourInput]) -> List[HourInput]:
        if len(v) != 24:
            raise ValueError(f"hours array must contain exactly 24 entries, received {len(v)}")
        hours_seen = [h.hour for h in v]
        if sorted(hours_seen) != list(range(24)):
            raise ValueError("hours array must cover hours 0 through 23 without gaps or duplicates")
        return v


# --- Structured Adjustments ---

class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of affected hours (0..23 in ascending order)")
    factor: float = Field(..., ge=0.0, le=1.0, description="Usable solar fraction remaining (0.0 to 1.0)")


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of affected hours (0..23 in ascending order)")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Elevated minimum reserve floor in kWh")


class WindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of affected hours (0..23 in ascending order)")


class MaxGridAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of affected hours (0..23 in ascending order)")
    max_grid_kwh: float = Field(..., ge=0.0, description="Maximum allowed grid import in kWh")


StructuredAdjustmentType = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
    None,
]


# --- Response Models ---

class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Index of the corresponding operator note")
    applies: bool = Field(..., description="true for active directives, false only for no_op")
    directive_type: DirectiveType = Field(..., description="Classification of the directive")
    structured_adjustment: StructuredAdjustmentType = Field(
        default=None,
        description="Structured adjustment payload or null if no_op",
    )
    explanation: str = Field(..., description="Concise explanation of the interpretation")


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0, description="Grid electricity imported in this hour")
    solar_used_kwh: float = Field(..., ge=0.0, description="Solar energy consumed in this hour")
    battery_action: BatteryAction = Field(..., description="Action taken: charge, discharge, or idle")
    battery_kwh: float = Field(..., ge=0.0, description="Magnitude of charge or discharge (0 when idle)")
    battery_energy_after_kwh: float = Field(..., ge=0.0, description="Battery energy state after this hour")


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str = Field(..., description="Echo of request scenario_id")
    directive_interpretation: List[DirectiveInterpretation] = Field(..., description="Interpretations in note_index order")
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24, description="24 hourly entries")
    total_grid_kwh: float = Field(..., ge=0.0, description="Total grid energy purchased")
    total_cost_bdt: float = Field(..., ge=0.0, description="Total cost of grid electricity in BDT")
    peak_grid_kwh: float = Field(..., ge=0.0, description="Peak hourly grid import")
    plan_summary: str = Field(..., description="Summary explanation of the strategy")


class HealthResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    error: str
    message: str
    status_code: int
