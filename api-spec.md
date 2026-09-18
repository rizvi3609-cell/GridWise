# GridWise LLM — HTTP API Specification

**Specification Standard**: OpenAPI 3.1.0 compatible  
**Service Title**: GridWise LLM Smart Campus Energy Optimizer  
**Base URL**: `http://localhost:8000` (Local) / `<DEPLOYED_HOST_URL>` (Production)  
**Content-Type**: `application/json`

---

## 1. Endpoints Overview

| Method | Endpoint | Description | Auth Required | Expected Latency |
|---|---|---|:---:|:---:|
| `GET` | `/health` | Service readiness probe for judge harness | No | $< 5\text{ms}$ |
| `POST` | `/optimize-energy` | LLM interpretation + 24-hour LP energy scheduling | No | $< 5.0\text{s}$ ($p95$) |

---

## 2. Endpoint: `GET /health`

The judging harness calls this endpoint to determine whether the service is alive, fully initialized, and ready to accept traffic.

### 2.1 Responses

#### HTTP 200 OK
Returned when the service and its optimization engine are fully ready.

```json
{
  "status": "ok"
}
```

---

## 3. Endpoint: `POST /optimize-energy`

Accepts a single 24-hour campus energy scenario with 1–3 natural-language operator notes, interprets all notes using an LLM, applies the resulting directives to an LP solver, and returns the machine-checkable interpretations alongside the mathematically optimal 24-hour hourly schedule.

### 3.1 Request Headers
- `Content-Type: application/json`
- `Accept: application/json`

---

### 3.2 Request Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["scenario_id", "operator_notes", "hours", "battery"],
  "properties": {
    "scenario_id": {
      "type": "string",
      "description": "Unique synthetic scenario identifier",
      "example": "GRID-101"
    },
    "operator_notes": {
      "type": "array",
      "minItems": 1,
      "maxItems": 3,
      "items": {
        "type": "string",
        "minLength": 1
      },
      "description": "Natural-language campus operator notes to interpret",
      "example": [
        "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
        "The sports office moved next month's registration deadline."
      ]
    },
    "hours": {
      "type": "array",
      "minItems": 24,
      "maxItems": 24,
      "description": "Array of exactly 24 hourly forecasts (hours 0 through 23)",
      "items": {
        "type": "object",
        "required": ["hour", "demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"],
        "properties": {
          "hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": "Unique integer from 0 to 23"
          },
          "demand_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Campus demand to be supplied in this hour"
          },
          "solar_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Base solar generation forecast before adjustments"
          },
          "tariff_bdt_per_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Grid electricity tariff in BDT for this hour"
          }
        }
      }
    },
    "battery": {
      "type": "object",
      "required": [
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour"
      ],
      "properties": {
        "capacity_kwh": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "description": "Maximum energy storage capacity of battery"
        },
        "initial_energy_kwh": {
          "type": "number",
          "minimum": 0.0,
          "description": "Battery energy at the start of hour 0"
        },
        "minimum_energy_kwh": {
          "type": "number",
          "minimum": 0.0,
          "description": "Base reserve level the battery must never fall below"
        },
        "max_charge_kwh_per_hour": {
          "type": "number",
          "minimum": 0.0,
          "description": "Maximum energy that can be charged in one hour"
        },
        "max_discharge_kwh_per_hour": {
          "type": "number",
          "minimum": 0.0,
          "description": "Maximum energy that can be discharged in one hour"
        }
      }
    }
  }
}
```

---

### 3.3 Response Schema (HTTP 200 OK)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary"
  ],
  "properties": {
    "scenario_id": {
      "type": "string",
      "description": "Must match the request scenario_id exactly"
    },
    "directive_interpretation": {
      "type": "array",
      "description": "One machine-checkable entry for every operator note in exact note_index order",
      "items": {
        "type": "object",
        "required": [
          "note_index",
          "applies",
          "directive_type",
          "structured_adjustment",
          "explanation"
        ],
        "properties": {
          "note_index": {
            "type": "integer",
            "minimum": 0,
            "description": "Zero-based index of corresponding operator note"
          },
          "applies": {
            "type": "boolean",
            "description": "true for applicable directives; false only for no_op"
          },
          "directive_type": {
            "type": "string",
            "enum": [
              "solar_reduction",
              "minimum_battery_reserve",
              "no_charge_window",
              "no_discharge_window",
              "max_grid_window",
              "no_op"
            ]
          },
          "structured_adjustment": {
            "description": "Specific adjustment parameters or null if no_op",
            "oneOf": [
              {
                "type": "null"
              },
              {
                "type": "object",
                "required": ["hours", "factor"],
                "properties": {
                  "hours": {"type": "array", "items": {"type": "integer"}},
                  "factor": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                }
              },
              {
                "type": "object",
                "required": ["hours", "minimum_energy_kwh"],
                "properties": {
                  "hours": {"type": "array", "items": {"type": "integer"}},
                  "minimum_energy_kwh": {"type": "number", "minimum": 0.0}
                }
              },
              {
                "type": "object",
                "required": ["hours"],
                "properties": {
                  "hours": {"type": "array", "items": {"type": "integer"}}
                }
              },
              {
                "type": "object",
                "required": ["hours", "max_grid_kwh"],
                "properties": {
                  "hours": {"type": "array", "items": {"type": "integer"}},
                  "max_grid_kwh": {"type": "number", "minimum": 0.0}
                }
              }
            ]
          },
          "explanation": {
            "type": "string",
            "description": "Short explanation of the interpretation"
          }
        }
      }
    },
    "hourly_plan": {
      "type": "array",
      "minItems": 24,
      "maxItems": 24,
      "description": "Exactly 24 hourly dispatch entries (hours 0 through 23)",
      "items": {
        "type": "object",
        "required": [
          "hour",
          "grid_kwh",
          "solar_used_kwh",
          "battery_action",
          "battery_kwh",
          "battery_energy_after_kwh"
        ],
        "properties": {
          "hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23
          },
          "grid_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Grid electricity purchased in this hour"
          },
          "solar_used_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Solar energy consumed; cannot exceed effective solar"
          },
          "battery_action": {
            "type": "string",
            "enum": ["charge", "discharge", "idle"]
          },
          "battery_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "Energy charged or discharged. Must be 0 when idle"
          },
          "battery_energy_after_kwh": {
            "type": "number",
            "minimum": 0.0,
            "description": "State of battery charge immediately following this hour"
          }
        }
      }
    },
    "total_grid_kwh": {
      "type": "number",
      "description": "Sum of grid_kwh across all 24 hours"
    },
    "total_cost_bdt": {
      "type": "number",
      "description": "Total electricity import cost in BDT"
    },
    "peak_grid_kwh": {
      "type": "number",
      "description": "Maximum single-hour grid import in the plan"
    },
    "plan_summary": {
      "type": "string",
      "description": "Concise summary of the optimization strategy"
    }
  }
}
```

---

## 4. HTTP Status Codes & Error Responses

The API follows strict standard HTTP status codes:

| Code | Meaning | When Triggered | Response Format |
|---|---|---|---|
| **200** | OK | Successful optimization & interpretation | Full response JSON schema |
| **400** | Bad Request | Malformed JSON, missing fields, hours length != 24 | Standard Error JSON |
| **422** | Unprocessable Entity | Semantically invalid numbers (e.g. initial energy > capacity) | Standard Error JSON |
| **500** | Internal Error | Controlled internal error. No stack traces or secrets | Standard Error JSON |

### Error Response Shape
```json
{
  "error": "Bad Request",
  "message": "Invalid request schema: field 'hours' must contain exactly 24 items.",
  "status_code": 400
}
```

> [!CAUTION]
> Stack traces, database strings, API keys, or raw system prompts are **never** included in HTTP 500 error bodies to strictly comply with Section 04 of the competition guidelines.

---

## 5. Concrete End-to-End Example

### Request:
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month'\''s registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 1, "demand_kwh": 85.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 2, "demand_kwh": 80.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 3, "demand_kwh": 80.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 4, "demand_kwh": 85.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 5, "demand_kwh": 95.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5},
      {"hour": 6, "demand_kwh": 110.0, "solar_kwh": 15.0, "tariff_bdt_per_kwh": 8.0},
      {"hour": 7, "demand_kwh": 130.0, "solar_kwh": 45.0, "tariff_bdt_per_kwh": 8.0},
      {"hour": 8, "demand_kwh": 160.0, "solar_kwh": 90.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 9, "demand_kwh": 190.0, "solar_kwh": 140.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 10, "demand_kwh": 210.0, "solar_kwh": 180.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 11, "demand_kwh": 220.0, "solar_kwh": 210.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 12, "demand_kwh": 215.0, "solar_kwh": 220.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 13, "demand_kwh": 205.0, "solar_kwh": 200.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 14, "demand_kwh": 195.0, "solar_kwh": 160.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 15, "demand_kwh": 180.0, "solar_kwh": 110.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 16, "demand_kwh": 170.0, "solar_kwh": 60.0, "tariff_bdt_per_kwh": 11.5},
      {"hour": 17, "demand_kwh": 175.0, "solar_kwh": 20.0, "tariff_bdt_per_kwh": 16.0},
      {"hour": 18, "demand_kwh": 200.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 16.0},
      {"hour": 19, "demand_kwh": 210.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 16.0},
      {"hour": 20, "demand_kwh": 190.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 16.0},
      {"hour": 21, "demand_kwh": 165.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 16.0},
      {"hour": 22, "demand_kwh": 135.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 8.0},
      {"hour": 23, "demand_kwh": 105.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 6.5}
    ],
    "battery": {
      "capacity_kwh": 300.0,
      "initial_energy_kwh": 120.0,
      "minimum_energy_kwh": 60.0,
      "max_charge_kwh_per_hour": 75.0,
      "max_discharge_kwh_per_hour": 75.0
    }
  }'
```

### Response:
```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar availability is reduced to 25% during the panel-cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    {"hour": 0, "grid_kwh": 165.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 75.0, "battery_energy_after_kwh": 195.0},
    {"hour": 1, "grid_kwh": 160.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 75.0, "battery_energy_after_kwh": 270.0},
    {"hour": 2, "grid_kwh": 110.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 30.0, "battery_energy_after_kwh": 300.0},
    {"hour": 3, "grid_kwh": 80.0, "solar_used_kwh": 0.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 4, "grid_kwh": 85.0, "solar_used_kwh": 0.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 5, "grid_kwh": 95.0, "solar_used_kwh": 0.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 6, "grid_kwh": 95.0, "solar_used_kwh": 15.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 7, "grid_kwh": 85.0, "solar_used_kwh": 45.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 8, "grid_kwh": 70.0, "solar_used_kwh": 90.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 9, "grid_kwh": 50.0, "solar_used_kwh": 140.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 10, "grid_kwh": 30.0, "solar_used_kwh": 180.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 11, "grid_kwh": 10.0, "solar_used_kwh": 210.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 12, "grid_kwh": 160.0, "solar_used_kwh": 55.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 13, "grid_kwh": 155.0, "solar_used_kwh": 50.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 14, "grid_kwh": 35.0, "solar_used_kwh": 160.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 15, "grid_kwh": 70.0, "solar_used_kwh": 110.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 16, "grid_kwh": 110.0, "solar_used_kwh": 60.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 300.0},
    {"hour": 17, "grid_kwh": 80.0, "solar_used_kwh": 20.0, "battery_action": "discharge", "battery_kwh": 75.0, "battery_energy_after_kwh": 225.0},
    {"hour": 18, "grid_kwh": 125.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 75.0, "battery_energy_after_kwh": 150.0},
    {"hour": 19, "grid_kwh": 135.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 75.0, "battery_energy_after_kwh": 75.0},
    {"hour": 20, "grid_kwh": 175.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 15.0, "battery_energy_after_kwh": 60.0},
    {"hour": 21, "grid_kwh": 165.0, "solar_used_kwh": 0.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 60.0},
    {"hour": 22, "grid_kwh": 135.0, "solar_used_kwh": 0.0, "battery_action": "idle", "battery_kwh": 0.0, "battery_energy_after_kwh": 60.0},
    {"hour": 23, "grid_kwh": 165.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 60.0, "battery_energy_after_kwh": 120.0}
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Charge during low off-peak tariff periods (hours 0-2 and 23), utilize available solar with 25% cleaning reduction in hours 12-13, discharge during peak evening tariff periods (hours 17-20) down to the 60 kWh base reserve floor, and maintain end-of-day battery neutrality at 120 kWh."
}
```
