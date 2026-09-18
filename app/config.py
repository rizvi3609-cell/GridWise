"""
Configuration and environment variable management for GridWise LLM.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root if present
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    # Service host & port (Must bind to 0.0.0.0 for Docker container)
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # LLM Provider Configuration
    # Supported keys: LLM_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY
    API_KEY: str = (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or ""
    )

    # Base URL for OpenAI-compatible endpoint
    # For OpenAI: https://api.openai.com/v1
    # For Groq: https://api.groq.com/openai/v1
    # For Gemini: https://generativelanguage.googleapis.com/v1beta/openai/
    BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

    # Model identifier
    MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # LLM timeout budget (seconds) to maintain overall p95 <= 5s
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "8.0"))

    # Enable offline heuristic fallback when API key is missing or model fails
    ALLOW_HEURISTIC_FALLBACK: bool = os.getenv("ALLOW_HEURISTIC_FALLBACK", "true").lower() in ("true", "1", "yes")


settings = Settings()
