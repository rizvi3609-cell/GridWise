"""
Comprehensive automated tests for GridWise LLM.
Tests GET /health, POST /optimize-energy across all 10 public sample cases,
and error handling on malformed requests.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """Verify GET /health returns HTTP 200 with status='ok'."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}


def test_all_10_public_sample_cases():
    """
    Runs all 10 sample cases through POST /optimize-energy.
    Verifies directive extraction, schedule validity, and cost optimality.
    """
    cases_file = Path(__file__).resolve().parent.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    with open(cases_file, "r") as f:
        cases_data = json.load(f)

    cases = cases_data["cases"]
    assert len(cases) == 10

    for case in cases:
        case_id = case["id"]
        inp = case["input"]
        exp = case["expected_output"]

        # Call POST /optimize-energy
        response = client.post("/optimize-energy", json=inp)
        assert response.status_code == 200, f"Case {case_id} failed with {response.text}"

        res_data = response.json()

        # 1. Echo scenario_id
        assert res_data["scenario_id"] == inp["scenario_id"]

        # 2. Check directive interpretation length and order
        interps = res_data["directive_interpretation"]
        exp_interps = exp["directive_interpretation"]
        assert len(interps) == len(exp_interps)

        for i, (actual_d, exp_d) in enumerate(zip(interps, exp_interps)):
            assert actual_d["note_index"] == i
            assert actual_d["directive_type"] == exp_d["directive_type"], (
                f"Case {case_id} note {i}: type {actual_d['directive_type']} != {exp_d['directive_type']}"
            )
            assert actual_d["applies"] == exp_d["applies"], (
                f"Case {case_id} note {i}: applies {actual_d['applies']} != {exp_d['applies']}"
            )

            if exp_d["applies"]:
                actual_adj = actual_d["structured_adjustment"]
                exp_adj = exp_d["structured_adjustment"]
                assert actual_adj["hours"] == exp_adj["hours"], (
                    f"Case {case_id} note {i}: hours {actual_adj['hours']} != {exp_adj['hours']}"
                )
                if "factor" in exp_adj:
                    assert abs(actual_adj["factor"] - exp_adj["factor"]) <= 0.01
                if "minimum_energy_kwh" in exp_adj:
                    assert abs(actual_adj["minimum_energy_kwh"] - exp_adj["minimum_energy_kwh"]) <= 0.01
                if "max_grid_kwh" in exp_adj:
                    assert abs(actual_adj["max_grid_kwh"] - exp_adj["max_grid_kwh"]) <= 0.01
            else:
                assert actual_d["structured_adjustment"] is None

        # 3. Check 24-hour plan validity
        plan = res_data["hourly_plan"]
        assert len(plan) == 24

        # 4. Check cost optimality
        cost_diff = abs(res_data["total_cost_bdt"] - exp["total_cost_bdt"])
        assert cost_diff <= 0.5, (
            f"Case {case_id}: total_cost_bdt {res_data['total_cost_bdt']} vs expected {exp['total_cost_bdt']}"
        )

        grid_diff = abs(res_data["total_grid_kwh"] - exp["total_grid_kwh"])
        assert grid_diff <= 0.5, (
            f"Case {case_id}: total_grid_kwh {res_data['total_grid_kwh']} vs expected {exp['total_grid_kwh']}"
        )

        peak_diff = abs(res_data["peak_grid_kwh"] - exp["peak_grid_kwh"])
        assert peak_diff <= 0.5, (
            f"Case {case_id}: peak_grid_kwh {res_data['peak_grid_kwh']} vs expected {exp['peak_grid_kwh']}"
        )


def test_malformed_requests():
    """Verify HTTP 400 is returned on structurally invalid input."""
    # 1. Missing scenario_id
    bad_req = {"operator_notes": ["Wash panels."], "hours": [], "battery": {}}
    res = client.post("/optimize-energy", json=bad_req)
    assert res.status_code == 400

    # 2. Incomplete hours (less than 24)
    bad_hours = {
        "scenario_id": "ERR-1",
        "operator_notes": ["Note"],
        "hours": [{"hour": 0, "demand_kwh": 10, "solar_kwh": 0, "tariff_bdt_per_kwh": 5}],
        "battery": {
            "capacity_kwh": 100,
            "initial_energy_kwh": 50,
            "minimum_energy_kwh": 10,
            "max_charge_kwh_per_hour": 20,
            "max_discharge_kwh_per_hour": 20,
        },
    }
    res = client.post("/optimize-energy", json=bad_hours)
    assert res.status_code == 400

    # 3. Invalid initial energy exceeding capacity
    bad_battery = {
        "scenario_id": "ERR-2",
        "operator_notes": ["Note"],
        "hours": [
            {"hour": h, "demand_kwh": 10, "solar_kwh": 0, "tariff_bdt_per_kwh": 5}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 100,
            "initial_energy_kwh": 150,  # exceeds capacity
            "minimum_energy_kwh": 10,
            "max_charge_kwh_per_hour": 20,
            "max_discharge_kwh_per_hour": 20,
        },
    }
    res = client.post("/optimize-energy", json=bad_battery)
    assert res.status_code == 400
