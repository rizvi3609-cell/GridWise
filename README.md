# GridWise LLM — Smart Campus Energy Optimization Service

[![Evaluation Ready](https://img.shields.io/badge/Status-Evaluation%20Ready-success.svg)]()
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)]()
[![HiGHS Solver](https://img.shields.io/badge/Solver-SciPy%20HiGHS-orange.svg)]()
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)]()

GridWise LLM is an intelligent microgrid energy scheduling service built for the **BUP CSE FEST 2026 Hackathon (Online Preliminary)**. The service interprets informal human operator notes using language intelligence, validates them through deterministic guardrails, and produces a mathematically optimal, cost-minimized 24-hour battery schedule using high-speed Linear Programming.

---

## 1. System Architecture Overview

The system strictly adheres to the core competition philosophy: **"Human notes are not directly trusted as math."**

```
   +-----------------------+
   | Energy Data & Notes   |
   +-----------------------+
               |
               v
   +-----------------------+
   |   LLM Interpreter     |  --> Semantic extraction with structured JSON output
   +-----------------------+
               |
               v
   +-----------------------+
   | Deterministic         |  --> Sorts hours (0..23), clamps factors [0,1],
   | Guardrails            |      enforces applies semantics, sanitizes distractors
   +-----------------------+
               |
               v
   +-----------------------+
   | SciPy HiGHS LP Solver |  --> Sub-millisecond continuous optimization
   +-----------------------+      (min total grid electricity cost in BDT)
               |
               v
   +-----------------------+
   |   Replay Auditor      |  --> Step-by-step verification of energy balance,
   +-----------------------+      battery limits, and end-of-day neutrality
               |
               v
   +-----------------------+
   |   HTTP API Response   |
   +-----------------------+
```

### Key Engineering Choices:
- **FastAPI + Uvicorn (ASGI)**: High concurrency, low-overhead asynchronous request handling.
- **SciPy HiGHS LP Solver**: Written in C++, solves the 24-hour dispatch problem in **$<3\text{ms}$** with zero external daemons or licensing constraints.
- **Deterministic Guardrails**: Guarantees that time windows are start-inclusive and end-exclusive (e.g. `1 PM to 3 PM` $\to [13, 14]$), hours are strictly sorted, and invalid outputs default safely to `no_op`.
- **Zero-Database Statelessness**: Eliminates all external database connection failures, migration locks, or latency penalties.

---

## 2. Quickstart (Local Reproduction)

### Prerequisites
- Python 3.11+ or 3.12+ (or `uv` / `pip`)
- `curl` (for testing)

### Step 1: Clone Repository and Enter Directory
```bash
git clone <YOUR_REPOSITORY_URL>
cd BUP_CSE_FEST_2026_Participant_Docs
```

### Step 2: Create Virtual Environment & Install Dependencies
Using `uv` (recommended, ultra-fast):
```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```
Or using standard `pip`:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy the template configuration:
```bash
cp .env.example .env
```
*(Optional: If connecting to a hosted LLM provider, edit `.env` and add your `LLM_API_KEY`. If left empty, the service uses its high-precision deterministic heuristic parser for 100% offline reproducibility).*

### Step 4: Start the Service
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
The service will bind to `0.0.0.0:8000` and display ready logs.

---

## 3. Verification & API Testing

### Test 1: Health Check (`GET /health`)
```bash
curl -X GET http://localhost:8000/health
```
**Expected Response:**
```json
{
  "status": "ok"
}
```

### Test 2: Run Automated Test Suite (All 10 Sample Cases)
Run the full pytest suite:
```bash
pytest tests/test_service.py -v
```
**Expected Output:**
```
tests/test_service.py::test_health_endpoint PASSED
tests/test_service.py::test_all_10_public_sample_cases PASSED
tests/test_service.py::test_malformed_requests PASSED
3 passed in ~1.15s
```

### Test 3: Public Sample Case Request (`POST /optimize-energy`)
Execute a test using `SAMPLE-01`:
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

**Key Expected Output Metrics:**
- `total_grid_kwh`: `2692.5`
- `total_cost_bdt`: `38365.0`
- `peak_grid_kwh`: `175.0`
- `directive_interpretation[0]`: `solar_reduction`, `hours: [12, 13]`, `factor: 0.25`
- `directive_interpretation[1]`: `no_op`, `applies: false`, `structured_adjustment: null`

---

## 4. Docker Fallback Execution

The included Dockerfile provides a tested, zero-secret container fallback for evaluation organizers.

### Build the Image
```bash
docker build -t gridwise-llm:latest .
```

### Run the Container
```bash
docker run -d --name gridwise-service -p 8000:8000 gridwise-llm:latest
```

### Test Container Health
```bash
curl -f http://localhost:8000/health
```

To stop and remove:
```bash
docker stop gridwise-service && docker rm gridwise-service
```

---

## 5. Environment Variables & Model Provider Configuration

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | IP interface to bind ASGI server |
| `PORT` | `8000` | Port for incoming HTTP requests |
| `LLM_API_KEY` | *(Empty)* | API Key for hosted LLM provider |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier (e.g., `gpt-4o-mini`, `gemini-2.5-flash`, `llama-3.3-70b-versatile`) |
| `LLM_TIMEOUT_SECONDS` | `8.0` | Max duration for LLM call before activating fallback |
| `ALLOW_HEURISTIC_FALLBACK` | `true` | Enables offline heuristic parser if LLM fails or API key is absent |

---

## 6. Security, Limitations & External Credits

### Security & Secret Handling:
- No API keys, credentials, or private tokens are hardcoded into the source code or Docker image.
- Controlled HTTP 500 error handlers catch exceptions without exposing stack traces, file paths, or configuration parameters.
- Uses only synthetic data provided by the challenge harness.

### Known Limitations:
- The optimization problem assumes whole-hour dispatch intervals ($h = 0 \dots 23$).
- Solar reduction factors and time windows apply at the 1-hour resolution.

### External Libraries & Credits:
- **FastAPI & Uvicorn**: High-performance Python web framework and ASGI server.
- **Pydantic V2**: Strict data validation and settings management.
- **SciPy (HiGHS)**: High-performance linear optimization solver.
- **HTTPX**: Asynchronous HTTP client.
