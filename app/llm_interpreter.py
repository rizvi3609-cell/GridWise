"""
LLM Directive Interpretation Engine with Resilient Fallback.
Uses an LLM via OpenAI-compatible endpoint when available,
and includes a deterministic semantic parser as an offline fallback.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings
from app.guardrails import sanitize_all_directives
from app.schemas import (
    BatteryInput,
    DirectiveInterpretation,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert energy management system assistant for the BUP campus microgrid.
Your task is to interpret 1 to 3 natural-language operator notes and extract structured directives.

Each operator note MUST be classified into EXACTLY ONE of the following directive types:
1. "solar_reduction": Usable solar output is reduced during specific hours.
   structured_adjustment: {"hours": [int, ...], "factor": float}
   NOTE: 'factor' is the fraction of usable solar REMAINING (e.g., an 80% reduction means factor = 0.2; 25% of forecast means factor = 0.25; half means factor = 0.5).
2. "minimum_battery_reserve": Battery energy must not drop below a required level during specific hours.
   structured_adjustment: {"hours": [int, ...], "minimum_energy_kwh": float}
   NOTE: If stated as a percentage (e.g., 50% of battery capacity), calculate minimum_energy_kwh = capacity_kwh * (percent / 100).
3. "no_charge_window": Battery charging is completely disabled during specific hours.
   structured_adjustment: {"hours": [int, ...]}
4. "no_discharge_window": Battery discharging is completely disabled during specific hours.
   structured_adjustment: {"hours": [int, ...]}
5. "max_grid_window": Grid electricity import cannot exceed a limit during specific hours.
   structured_adjustment: {"hours": [int, ...], "max_grid_kwh": float}
6. "no_op": The note is an unrelated campus notice (e.g., cafeteria menus, sports events, library hours, seminar bookings, club notices) or does not affect the energy schedule.
   applies: false
   structured_adjustment: null

12-HOUR TO 24-HOUR CLOCK CONVERSION (CRITICAL):
- 12 AM (midnight) = 0
- 1 AM = 1, 2 AM = 2, 3 AM = 3, 4 AM = 4, 5 AM = 5, 6 AM = 6, 7 AM = 7, 8 AM = 8, 9 AM = 9, 10 AM = 10, 11 AM = 11
- 12 PM (noon) = 12
- 1 PM = 13, 2 PM = 14, 3 PM = 15, 4 PM = 16, 5 PM = 17, 6 PM = 18, 7 PM = 19, 8 PM = 20, 9 PM = 21, 10 PM = 22, 11 PM = 23

TIME WINDOW CONVENTION (START-INCLUSIVE, END-EXCLUSIVE):
The start hour is included, the end hour is EXCLUDED!
- "from 1 PM to 3 PM" (13:00 to 15:00) -> [13, 14]
- "from noon until 2 PM" (12:00 to 14:00) -> [12, 13]
- "from 2 AM until 5 AM" (02:00 to 05:00) -> [2, 3, 4]
- "from 6 PM until 9 PM" (18:00 to 21:00) -> [18, 19, 20]  (Notice 21 is excluded!)
- "from 6 PM until 8 PM" (18:00 to 20:00) -> [18, 19]      (Notice 20 is excluded!)
- "from 6 PM until 10 PM" (18:00 to 22:00) -> [18, 19, 20, 21]
- "from 7 PM until 9 PM" (19:00 to 21:00) -> [19, 20]
- "from 7 PM until 10 PM" (19:00 to 22:00) -> [19, 20, 21]
- "between 11 AM and 2 PM" (11:00 to 14:00) -> [11, 12, 13]
- "from 10 AM until noon" (10:00 to 12:00) -> [10, 11]
- "from 2 PM until 4 PM" (14:00 to 16:00) -> [14, 15]

OUTPUT FORMAT:
Return a valid JSON object with a single top-level key "directives" containing a list of objects in note_index order:
{
  "directives": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "Solar availability is reduced during panel cleaning."
    }
  ]
}
"""


# --- Resilient Heuristic Fallback Parser ---

def _parse_hour_token(token: str) -> Optional[int]:
    token = token.strip().lower()
    if token in ("noon", "12 pm"):
        return 12
    if token in ("midnight", "12 am"):
        return 0
    m = re.match(r"^(\d{1,2})(?::00)?\s*(am|pm)?$", token)
    if not m:
        return None
    val = int(m.group(1))
    period = m.group(2)
    if period == "pm" and val != 12:
        val += 12
    elif period == "am" and val == 12:
        val = 0
    return val


def _extract_time_window(text: str) -> List[int]:
    text_lower = text.lower()
    patterns = [
        r"(?:from|between)\s+([0-9]{1,2}(?::00)?(?:\s*(?:am|pm))?|noon|midnight)\s+(?:until|to|and)\s+([0-9]{1,2}(?::00)?(?:\s*(?:am|pm))?|noon|midnight)",
        r"([0-9]{1,2})\s*-\s*([0-9]{1,2})\s*(am|pm)",
    ]
    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            if len(m.groups()) == 3 and m.group(3):
                h1_raw = m.group(1) + " " + m.group(3)
                h2_raw = m.group(2) + " " + m.group(3)
                h1 = _parse_hour_token(h1_raw)
                h2 = _parse_hour_token(h2_raw)
            else:
                h1_str = m.group(1)
                h2_str = m.group(2)
                if "am" not in h1_str and "pm" not in h1_str and h1_str not in ("noon", "midnight"):
                    if "pm" in h2_str:
                        h1_val_m = re.match(r"\d+", h1_str)
                        h2_val_m = re.match(r"\d+", h2_str)
                        if h1_val_m and h2_val_m:
                            h1_val = int(h1_val_m.group())
                            h2_val = int(h2_val_m.group())
                            if h1_val != 12 and h1_val <= h2_val:
                                h1_str += " pm"
                    elif "am" in h2_str:
                        h1_str += " am"
                h1 = _parse_hour_token(h1_str)
                h2 = _parse_hour_token(h2_str)
            if h1 is not None and h2 is not None and h1 < h2:
                return list(range(h1, h2))
    return []


def heuristic_interpret_note(
    note: str,
    note_idx: int,
    battery: BatteryInput,
) -> Dict[str, Any]:
    """
    Deterministically extracts directives from common phrasing patterns.
    """
    text = note.strip()
    text_lower = text.lower()
    hours = _extract_time_window(text)

    # Distractor check
    distractor_words = [
        "cafeteria", "sports office", "library", "registration deadline",
        "club notices", "seminar room", "book-return", "student affairs"
    ]
    if any(w in text_lower for w in distractor_words) or not hours:
        return {
            "note_index": note_idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "This note does not affect today's 24-hour energy schedule.",
        }

    # 1. Solar Reduction
    if any(w in text_lower for w in ("solar", "pv", "panels", "inverter", "cloud cover", "washing")):
        factor = 1.0
        m_red = re.search(r"(\d+)%\s*reduction", text_lower)
        if m_red:
            factor = max(0.0, 1.0 - (float(m_red.group(1)) / 100.0))
        else:
            m_pct = re.search(r"(?:to\s*about|roughly|leave)\s*(\d+)%", text_lower)
            if m_pct:
                factor = float(m_pct.group(1)) / 100.0
            elif "half" in text_lower:
                factor = 0.5
            elif "one-fifth" in text_lower:
                factor = 0.2
            elif "one-quarter" in text_lower or "quarter" in text_lower:
                factor = 0.25

        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": hours, "factor": round(factor, 4)},
            "explanation": "Solar availability adjusted during window.",
        }

    # 2. No Charge Window
    if any(w in text_lower for w in ("charger", "charging", "charge")) and any(
        w in text_lower for w in ("isolated", "unavailable", "disabled", "not charge", "prohibited", "outage")
    ):
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery charging is disabled during this window.",
        }

    # 3. No Discharge Window
    if "discharge" in text_lower and any(
        w in text_lower for w in ("not discharge", "do not discharge", "disabled", "prohibited")
    ):
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery discharge is disabled during this window.",
        }

    # 4. Minimum Battery Reserve
    if any(w in text_lower for w in ("reserve", "remain in the battery", "stored in the battery", "keep at least")):
        m_pct = re.search(r"(\d+)%\s*of\s*(?:the\s*)?battery\s*capacity", text_lower)
        reserve_kwh = battery.minimum_energy_kwh
        if m_pct:
            pct = float(m_pct.group(1)) / 100.0
            reserve_kwh = pct * battery.capacity_kwh
        else:
            m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text_lower)
            if m_kwh:
                reserve_kwh = float(m_kwh.group(1))

        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": hours,
                "minimum_energy_kwh": round(reserve_kwh, 4),
            },
            "explanation": "Battery reserve floor elevated during window.",
        }

    # 5. Max Grid Window
    if any(w in text_lower for w in ("grid", "feeder", "transformer", "substation", "intake")):
        m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text_lower)
        grid_cap = 0.0
        if m_kwh:
            grid_cap = float(m_kwh.group(1))

        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {
                "hours": hours,
                "max_grid_kwh": round(grid_cap, 4),
            },
            "explanation": "Grid import capped during window.",
        }

    # Default fallback
    return {
        "note_index": note_idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "Note does not affect today's schedule.",
    }


# --- LLM API Call with Async HTTP ---

async def call_llm_api(
    notes: List[str],
    battery: BatteryInput,
) -> Optional[List[Dict[str, Any]]]:
    """
    Calls OpenAI-compatible LLM endpoint using structured JSON formatting.
    """
    if not settings.API_KEY:
        return None

    user_prompt = f"Battery Capacity: {battery.capacity_kwh} kWh, Base Min Reserve: {battery.minimum_energy_kwh} kWh.\n\n"
    user_prompt += "Operator Notes to Interpret:\n"
    for idx, note in enumerate(notes):
        user_prompt += f"[{idx}] \"{note}\"\n"

    payload = {
        "model": settings.MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }

    url = f"{settings.BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "directives" in parsed:
                    return parsed["directives"]
                elif isinstance(parsed, list):
                    return parsed
            else:
                logger.warning("LLM API returned status %d: %s", response.status_code, response.text)
    except Exception as exc:
        logger.warning("LLM API call failed or timed out: %s", exc)

    return None


async def interpret_operator_notes(
    notes: List[str],
    battery: BatteryInput,
) -> List[DirectiveInterpretation]:
    """
    Interprets notes via LLM with deterministic guardrail sanitization and clock reconciliation.
    """
    raw_directives: Optional[List[Dict[str, Any]]] = None

    # 1. Attempt LLM API call if API key configured
    if settings.API_KEY:
        try:
            raw_directives = await call_llm_api(notes, battery)
        except Exception as exc:
            logger.error("Error invoking LLM: %s", exc)

    # 2. If LLM unavailable or returned invalid output, use heuristic fallback
    if not raw_directives:
        if settings.ALLOW_HEURISTIC_FALLBACK:
            raw_directives = [
                heuristic_interpret_note(note, idx, battery)
                for idx, note in enumerate(notes)
            ]
        else:
            raw_directives = [
                {
                    "note_index": idx,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "No LLM response available.",
                }
                for idx in range(len(notes))
            ]

    # 3. Deterministic Guardrail Time-Reconciliation:
    # Use deterministic clock parsing to prevent LLM off-by-one errors on time windows
    for i, note in enumerate(notes):
        if i < len(raw_directives):
            d = raw_directives[i]
            if d.get("applies") and d.get("directive_type") != "no_op":
                exact_hours = _extract_time_window(note)
                if exact_hours:
                    adj = d.get("structured_adjustment") or {}
                    adj["hours"] = exact_hours
                    d["structured_adjustment"] = adj

    # 4. Always pass through deterministic guardrail sanitizer
    return sanitize_all_directives(raw_directives, len(notes), battery)
