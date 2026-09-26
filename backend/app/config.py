"""Runtime configuration with safe local defaults and a persistent production data root."""
import os
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.getenv("APP_DATA_DIR", BACKEND_DIRECTORY)).resolve()


def cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_URL", "").strip()
    if configured:
        return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]
