import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.api.auth import router as auth_router
from app.database import initialize_database
from app.config import DATA_DIRECTORY, cors_origins


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


app = FastAPI(
    title="AI Video Editor API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def setup_application_database() -> None:
    initialize_database()


app.include_router(auth_router)
app.include_router(projects_router)

@app.get("/health")
def health_check() -> dict[str, str]:
    """Confirm that the backend server is running."""
    return {"status": "ok"}


@app.get("/config-status")
def config_status() -> dict[str, bool]:
    """Report only whether Gemini configuration exists, never the secret itself."""
    return {"gemini_api_key_configured": bool(os.getenv("GEMINI_API_KEY"))}
