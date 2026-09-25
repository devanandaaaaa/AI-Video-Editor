import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.projects import router as projects_router


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


app = FastAPI(
    title="AI Video Editor API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)

# Rendered videos are public; uploads and application configuration remain private.
OUTPUTS_DIRECTORY = Path(__file__).resolve().parents[1] / "outputs"
OUTPUTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIRECTORY), name="outputs")


@app.get("/health")
def health_check() -> dict[str, str]:
    """Confirm that the backend server is running."""
    return {"status": "ok"}


@app.get("/config-status")
def config_status() -> dict[str, bool]:
    """Report only whether Gemini configuration exists, never the secret itself."""
    return {"gemini_api_key_configured": bool(os.getenv("GEMINI_API_KEY"))}
