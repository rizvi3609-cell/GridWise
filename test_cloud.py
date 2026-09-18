"""
Interactive script to test your live Render cloud deployment with any sample case.
Usage:
    .venv/bin/python test_cloud.py
"""

import json
import sys
import time
import httpx

CLOUD_URL = "https://gridwise-ccu1.onrender.com"

def main():
    print("=" * 65)
    print(f"  Testing Live Cloud Service: {CLOUD_URL}")
    print("=" * 65)

    # 1. Quick Health Check
    try:
        r_health = httpx.get(f"{CLOUD_URL}/health", timeout=10.0)
        print(f"[1] GET /health -> Status: {r_health.status_code} ({r_health.text})")
    except Exception as e:
        print(f"[!] Health check failed: {e}")
        return

    # 2. Load Sample Cases
    with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json") as f:
        cases = json.load(f)["cases"]

    # Select case
    case_num = 1
    if len(sys.argv) > 1:
        try:
            case_num = int(sys.argv[1])
        except ValueError:
            case_num = 1
    else:
        print(f"\nAvailable cases: 1 to {len(cases)}")
        try:
            user_in = input("Select case number (1-10) [default: 1]: ").strip()
            if user_in:
                case_num = int(user_in)
        except (ValueError, EOFError):
            case_num = 1

    case_num = max(1, min(len(cases), case_num))
    selected_case = cases[case_num - 1]
    case_id = selected_case["id"]
    case_label = selected_case["label"]

    print(f"\n--- Testing Case {case_num}: {case_id} ({case_label}) ---")
    print("Operator Notes:")
    for i, note in enumerate(selected_case["input"]["operator_notes"]):
        print(f"  [{i}] \"{note}\"")

    print("\nSending request to cloud server...")
    t0 = time.perf_counter()
    try:
        response = httpx.post(
            f"{CLOUD_URL}/optimize-energy",
            json=selected_case["input"],
            timeout=35.0,
        )
        elapsed_sec = time.perf_counter() - t0
        print(f"Status Code: {response.status_code} (took {elapsed_sec:.2f} seconds)")

        if response.status_code == 200:
            data = response.json()
            expected = selected_case["expected_output"]

            print("\n[+] Directives Extracted by Cloud LLM:")
            for d in data["directive_interpretation"]:
                applies_str = "ACTIVE" if d["applies"] else "IGNORED (no_op)"
                print(f"    [{d['note_index']}] {d['directive_type']} -> {applies_str}")
                if d["structured_adjustment"]:
                    print(f"        Adjustment: {d['structured_adjustment']}")
                print(f"        Explanation: {d['explanation']}")

            print("\n[+] Optimization Results Comparison:")
            calc_cost = data["total_cost_bdt"]
            exp_cost = expected["total_cost_bdt"]
            calc_grid = data["total_grid_kwh"]
            exp_grid = expected["total_grid_kwh"]

            print(f"    Total Cost:     {calc_cost:.2f} BDT  (Organizer Benchmark: {exp_cost:.2f} BDT)")
            print(f"    Total Grid kWh: {calc_grid:.2f} kWh  (Organizer Benchmark: {exp_grid:.2f} kWh)")
            print(f"    Peak Grid:      {data['peak_grid_kwh']:.2f} kWh  (Organizer Benchmark: {expected['peak_grid_kwh']:.2f} kWh)")

            cost_diff = abs(calc_cost - exp_cost)
            if cost_diff <= 0.05:
                print("\n>>> RESULT: 100% PERFECT MATCH (0.00 BDT difference)! <<<")
            else:
                print(f"\n>>> RESULT: Cost delta is {cost_diff:.2f} BDT <<<")

            print(f"\nPlan Summary: {data['plan_summary']}")
        else:
            print("Error from server:", response.text)

    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    main()
