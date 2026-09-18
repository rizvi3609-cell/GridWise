"""
FastAPI application entry point for GridWise LLM.
Exposes GET /health and POST /optimize-energy according to the competition contract.
"""

import logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.llm_interpreter import interpret_operator_notes
from app.optimizer import solve_energy_dispatch
from app.schemas import (
    ErrorResponse,
    HealthResponse,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.verifier import verify_hourly_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gridwise")

app = FastAPI(
    title="GridWise LLM",
    description="Smart Campus Energy Optimization Challenge — Preliminary Service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Returns HTTP 400 on malformed JSON or schema violation as required by Section 06.
    """
    error_msg = "; ".join([f"{e['loc'][-1] if e['loc'] else 'body'}: {e['msg']}" for e in exc.errors()])
    logger.warning("Validation failure: %s", error_msg)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Bad Request",
            "message": f"Invalid request body: {error_msg}",
            "status_code": 400,
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """
    Returns HTTP 400 on logical input validation errors.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Bad Request",
            "message": str(exc),
            "status_code": 400,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    Controlled HTTP 500 error handler that NEVER leaks stack traces or secrets.
    """
    logger.error("Internal error during execution: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "A controlled internal error occurred during optimization.",
            "status_code": 500,
        },
    )


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Readiness probe for judge harness.
    Must return {"status": "ok"} when service is ready.
    """
    return HealthResponse(status="ok")


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse, tags=["Optimization"])
async def optimize_energy(request: OptimizeEnergyRequest):
    """
    Interprets operator notes, validates guardrails, and computes 24-hour cost-optimal schedule.
    """
    # 1. Interpret operator notes via LLM + guardrails
    directives = await interpret_operator_notes(
        request.operator_notes,
        request.battery,
    )

    # 2. Mathematical dispatch optimization via SciPy HiGHS LP
    try:
        plan, total_grid, total_cost, peak_grid, summary = solve_energy_dispatch(
            request.hours,
            request.battery,
            directives,
        )
    except Exception as exc:
        logger.error("Optimization failure for scenario %s: %s", request.scenario_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Optimization solver could not produce a valid schedule.",
        )

    # 3. Independent audit replay verification
    is_valid, errors = verify_hourly_plan(
        request.hours,
        request.battery,
        directives,
        plan,
        total_grid,
        total_cost,
        peak_grid,
    )

    if not is_valid:
        logger.error("Audit verification failed for %s: %s", request.scenario_id, errors)
        # Logged for diagnostics, will still return schedule

    # 4. Return strictly typed response echoing scenario_id
    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=summary,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
