import logging
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.services.embedding_service import store_project_scene_embeddings
from app.services.frame_extraction_service import extract_project_frames
from app.services.scene_description_service import describe_project_frames
from app.services.semantic_matching_service import match_script_beats_to_scenes
from app.services.rough_cut_selection_service import create_rough_cut_selection_plan
from app.services.rough_cut_render_service import render_rough_cut
from app.services.script_service import split_script_into_beats

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = logging.getLogger(__name__)

UPLOADS_DIRECTORY = Path(__file__).resolve().parents[2] / "uploads"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}


class SemanticMatchInput(BaseModel):
    """The fields needed from one existing semantic-matching result."""

    beat_number: int
    beat_text: str
    matched_scene_number: int
    clip_name: str
    frame_number: int


class RoughCutSelectionRequest(BaseModel):
    """Existing semantic matches used to create a plan without re-querying AI."""

    matches: list[SemanticMatchInput]


class RoughCutRenderSelection(BaseModel):
    """One previously prepared source segment to include in the rough cut."""

    beat_number: int
    beat_text: str
    matched_scene_number: int
    clip_name: str
    source_video_path: str
    matched_timestamp_seconds: float
    source_clip_duration: float
    segment_start_seconds: float
    segment_end_seconds: float


class RoughCutRenderRequest(BaseModel):
    """The rough-cut selection plan to render without changing it."""

    selections: list[RoughCutRenderSelection]


def get_project_directory(project_id: str) -> Path:
    try:
        UUID(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Project not found.") from error

    project_directory = UPLOADS_DIRECTORY / project_id
    if not project_directory.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return project_directory


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_project_files(
    script: UploadFile = File(...),
    videos: list[UploadFile] = File(...),
) -> dict[str, object]:
    """Save one text script and one or more raw clips for a new project."""
    if not script.filename or Path(script.filename).suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="The script must be a .txt file.")

    if not videos:
        raise HTTPException(status_code=400, detail="Upload at least one video clip.")

    invalid_videos = [
        video.filename for video in videos
        if not video.filename or Path(video.filename).suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS
    ]
    if invalid_videos:
        raise HTTPException(
            status_code=400,
            detail="Videos must use MP4, MOV, or WEBM format.",
        )

    project_id = str(uuid4())
    project_directory = UPLOADS_DIRECTORY / project_id
    project_directory.mkdir(parents=True, exist_ok=False)

    script_destination = project_directory / "script.txt"
    script_destination.write_bytes(await script.read())

    saved_clips: list[str] = []
    for index, video in enumerate(videos, start=1):
        extension = Path(video.filename).suffix.lower()
        clip_name = f"clip_{index}{extension}"
        (project_directory / clip_name).write_bytes(await video.read())
        saved_clips.append(clip_name)

    return {
        "project_id": project_id,
        "script_file": script_destination.name,
        "clip_count": len(saved_clips),
        "clips": saved_clips,
        "message": "Files uploaded. Ready for scene analysis.",
    }


@router.get("/{project_id}/script-beats")
def get_script_beats(project_id: str) -> dict[str, object]:
    """Return ordered narrative beats from an uploaded script."""
    project_directory = get_project_directory(project_id)
    script_path = project_directory / "script.txt"
    script_text = script_path.read_text(encoding="utf-8-sig").strip()
    if not script_text:
        raise HTTPException(status_code=400, detail="The uploaded script is empty.")

    beats = split_script_into_beats(script_text)
    return {
        "project_id": project_id,
        "beat_count": len(beats),
        "beats": beats,
    }


@router.post("/{project_id}/extract-frames")
def extract_frames(project_id: str) -> dict[str, object]:
    """Sample still frames locally so the next phase can describe visual scenes."""
    project_directory = get_project_directory(project_id)
    try:
        clips = extract_project_frames(project_directory)
    except (subprocess.CalledProcessError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"Frame extraction failed: {error}") from error

    return {
        "project_id": project_id,
        "clip_count": len(clips),
        "clips": clips,
    }


@router.post("/{project_id}/describe-scenes")
def describe_scenes(project_id: str) -> dict[str, object]:
    """Ask Gemini to describe the previously extracted visual scene frames."""
    project_directory = get_project_directory(project_id)
    try:
        result = describe_project_frames(project_directory)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Gemini scene description failed")
        raise HTTPException(status_code=502, detail="Gemini scene description failed.") from error

    return {"project_id": project_id, **result}


@router.post("/{project_id}/store-scene-embeddings")
def store_scene_embeddings(project_id: str) -> dict[str, object]:
    """Persist Gemini embeddings for the project's saved scene descriptions."""
    project_directory = get_project_directory(project_id)
    try:
        result = store_project_scene_embeddings(project_id, project_directory)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Scene embedding storage failed")
        raise HTTPException(status_code=502, detail="Scene embedding storage failed.") from error

    return {"project_id": project_id, **result}


@router.post("/{project_id}/match-script-beats")
def match_script_beats(project_id: str) -> dict[str, object]:
    """Match every script beat to its nearest stored video scene."""
    project_directory = get_project_directory(project_id)
    try:
        matches = match_script_beats_to_scenes(project_id, project_directory)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Semantic scene matching failed")
        raise HTTPException(status_code=502, detail="Semantic scene matching failed.") from error

    return {
        "project_id": project_id,
        "beat_count": len(matches),
        "matches": matches,
    }


@router.post("/{project_id}/prepare-rough-cut")
def prepare_rough_cut(
    project_id: str, request: RoughCutSelectionRequest
) -> dict[str, object]:
    """Prepare source-video selections from existing semantic match results."""
    project_directory = get_project_directory(project_id)
    try:
        plan = create_rough_cut_selection_plan(
            project_directory,
            [match.model_dump() for match in request.matches],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Rough-cut selection planning failed")
        raise HTTPException(status_code=502, detail="Rough-cut selection planning failed.") from error

    return {
        "project_id": project_id,
        "selection_count": len(plan),
        "selections": plan,
    }


@router.post("/{project_id}/render-rough-cut")
def render_project_rough_cut(
    project_id: str, request: RoughCutRenderRequest
) -> dict[str, object]:
    """Render a new MP4 from an existing rough-cut selection plan."""
    project_directory = get_project_directory(project_id)
    try:
        result = render_rough_cut(
            project_id,
            project_directory,
            [selection.model_dump() for selection in request.selections],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        logger.exception("Rough-cut rendering failed")
        raise HTTPException(status_code=500, detail=str(error)) from error

    return {"project_id": project_id, **result}
