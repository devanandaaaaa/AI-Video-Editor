import logging
import subprocess
from pathlib import Path
import shutil
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services.embedding_service import store_project_scene_embeddings
from app.services.frame_extraction_service import extract_project_frames
from app.services.scene_description_service import describe_project_frames
from app.services.semantic_matching_service import match_script_beats_to_scenes
from app.services.rough_cut_selection_service import create_rough_cut_selection_plan
from app.services.rough_cut_render_service import render_rough_cut
from app.services.script_service import split_script_into_beats
from app.services.audio_processing_service import MAX_AUDIO_BYTES, analyze_voiceover, get_voiceover_beats
from app.api.auth import get_current_user
from app.database import connection
from app.config import DATA_DIRECTORY

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = logging.getLogger(__name__)

UPLOADS_DIRECTORY = DATA_DIRECTORY / "uploads"
OUTPUTS_DIRECTORY = DATA_DIRECTORY / "outputs"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".webm"}


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


def get_project_directory(project_id: str, user_id: int) -> Path:
    try:
        UUID(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Project not found.") from error

    with connection() as db:
        project = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    project_directory = UPLOADS_DIRECTORY / project_id
    if not project_directory.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return project_directory


def update_project_status(project_id: str, status_value: str) -> None:
    with connection() as db:
        db.execute("UPDATE projects SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status_value, project_id))


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_project_files(
    script: UploadFile | None = File(None),
    voiceover: UploadFile | None = File(None),
    videos: list[UploadFile] = File(...),
    name: str = Form("Untitled project"),
    template_id: int | None = Form(None),
    user: dict[str, object] = Depends(get_current_user),
) -> dict[str, object]:
    """Save voiceover/legacy script and raw clips for the authenticated user."""
    if not voiceover and not script:
        raise HTTPException(status_code=400, detail="Upload a voiceover audio file (or a legacy TXT script).")
    if script and (not script.filename or Path(script.filename).suffix.lower() != ".txt"):
        raise HTTPException(status_code=400, detail="The legacy script must be a .txt file.")
    if voiceover and (not voiceover.filename or Path(voiceover.filename).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Voiceover must use MP3, WAV, M4A, AAC, OGG, or WEBM format.")

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

    with connection() as db:
        template = None
        if template_id is not None:
            template = db.execute("SELECT id FROM templates WHERE id=? AND active=1", (template_id,)).fetchone()
        if template_id is not None and not template:
            raise HTTPException(status_code=400, detail="Selected template was not found.")

    project_id = str(uuid4())
    project_directory = UPLOADS_DIRECTORY / project_id
    project_directory.mkdir(parents=True, exist_ok=False)
    with connection() as db:
        db.execute("""INSERT INTO projects (id, user_id, name, template_id, script_file, audio_file, status)
                      VALUES (?, ?, ?, ?, NULL, NULL, 'uploading')""",
                   (project_id, user["id"], name.strip()[:120] or "Untitled project", template_id))

    script_destination = None
    audio_destination = None
    try:
        if script:
            script_destination = project_directory / "script.txt"
            script_destination.write_bytes(await script.read())
        if voiceover:
            audio_destination = project_directory / f"voiceover{Path(voiceover.filename).suffix.lower()}"
            audio_bytes = await voiceover.read()
            if len(audio_bytes) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=400, detail="Voiceover exceeds the 20 MB processing limit.")
            audio_destination.write_bytes(audio_bytes)

        saved_clips: list[str] = []
        for index, video in enumerate(videos, start=1):
            extension = Path(video.filename).suffix.lower()
            clip_name = f"clip_{index}{extension}"
            (project_directory / clip_name).write_bytes(await video.read())
            saved_clips.append(clip_name)

        with connection() as db:
            db.execute("""UPDATE projects SET script_file=?, audio_file=?, status='created', updated_at=CURRENT_TIMESTAMP
                          WHERE id=?""", (script_destination.name if script_destination else None,
                                               audio_destination.name if audio_destination else None, project_id))
    except Exception:
        update_project_status(project_id, "failed")
        shutil.rmtree(project_directory, ignore_errors=True)
        raise
    return {
        "project_id": project_id,
        "script_file": script_destination.name if script_destination else None,
        "audio_file": audio_destination.name if audio_destination else None,
        "clip_count": len(saved_clips),
        "clips": saved_clips,
        "message": "Files uploaded. Ready for scene analysis.",
    }


@router.get("")
def list_projects(user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    with connection() as db:
        rows = db.execute("""SELECT p.id, p.name, p.status, p.audio_file, p.created_at, p.updated_at,
                                  p.output_video_path, p.output_duration_seconds, p.output_file_size_bytes,
                                  t.name AS template_name
                           FROM projects p LEFT JOIN templates t ON t.id=p.template_id
                           WHERE p.user_id=? ORDER BY p.created_at DESC""", (user["id"],)).fetchall()
    return {"projects": [dict(row) for row in rows]}


@router.get("/templates")
def list_templates(user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    with connection() as db:
        rows = db.execute("SELECT id, slug, name, description, output_width, output_height FROM templates WHERE active=1").fetchall()
    return {"templates": [dict(row) for row in rows]}


@router.get("/{project_id}")
def get_project(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Return one authenticated project's persisted workspace and export details."""
    get_project_directory(project_id, int(user["id"]))
    with connection() as db:
        row = db.execute("""SELECT p.id, p.name, p.status, p.script_file, p.audio_file, p.created_at, p.updated_at,
                                  p.output_video_path, p.output_duration_seconds, p.output_file_size_bytes,
                                  t.id AS template_id, t.name AS template_name, t.description AS template_description,
                                  t.output_width, t.output_height
                           FROM projects p LEFT JOIN templates t ON t.id=p.template_id
                           WHERE p.id=? AND p.user_id=?""", (project_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return dict(row)


@router.get("/{project_id}/output")
def download_project_output(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> FileResponse:
    """Stream only the authenticated owner's rendered MP4."""
    with connection() as db:
        row = db.execute("SELECT output_video_path FROM projects WHERE id=? AND user_id=?", (project_id, user["id"])).fetchone()
    if not row or not row["output_video_path"]:
        raise HTTPException(status_code=404, detail="No completed video is available for this project.")
    output_root = OUTPUTS_DIRECTORY.resolve()
    output_path = (OUTPUTS_DIRECTORY / row["output_video_path"]).resolve()
    try:
        output_path.relative_to(output_root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Output file was not found.") from error
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output file was not found.")
    return FileResponse(output_path, media_type="video/mp4", filename=output_path.name)


@router.get("/{project_id}/audio")
def audio_status(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    directory = get_project_directory(project_id, int(user["id"]))
    with connection() as db:
        row = db.execute("SELECT audio_file FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row or not row["audio_file"]:
        raise HTTPException(status_code=400, detail="This legacy project has no voiceover audio.")
    analysis_path = directory / "voiceover_analysis.json"
    if analysis_path.is_file():
        import json
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        return {"project_id": project_id, "audio_file": row["audio_file"], "transcription_status": "complete", "analysis": analysis}
    return {"project_id": project_id, "audio_file": row["audio_file"], "transcription_status": "pending"}


@router.post("/{project_id}/understand-voiceover")
def understand_voiceover(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Use Gemini to produce the authenticated project's real transcript and story beats."""
    directory = get_project_directory(project_id, int(user["id"]))
    with connection() as db:
        row = db.execute("SELECT audio_file FROM projects WHERE id=? AND user_id=?", (project_id, user["id"])).fetchone()
    if not row or not row["audio_file"]:
        raise HTTPException(status_code=400, detail="This project needs a voiceover audio file.")
    update_project_status(project_id, "processing_audio")
    try:
        result = analyze_voiceover(directory, row["audio_file"])
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        update_project_status(project_id, "failed")
        logger.exception("Gemini voiceover understanding failed")
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"project_id": project_id, **result}


@router.get("/{project_id}/script-beats")
def get_script_beats(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Return audio-derived beats, retaining TXT behavior for legacy projects."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    if (project_directory / "voiceover_analysis.json").is_file():
        beats = get_voiceover_beats(project_directory)
    else:
        script_path = project_directory / "script.txt"
        if not script_path.is_file():
            raise HTTPException(status_code=400, detail="Run understand-voiceover before requesting story beats.")
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
def extract_frames(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Sample still frames locally so the next phase can describe visual scenes."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    update_project_status(project_id, "extracting_frames")
    try:
        clips = extract_project_frames(project_directory)
    except (subprocess.CalledProcessError, ValueError) as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=f"Frame extraction failed: {error}") from error
    return {
        "project_id": project_id,
        "clip_count": len(clips),
        "clips": clips,
    }


@router.post("/{project_id}/describe-scenes")
def describe_scenes(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Ask Gemini to describe the previously extracted visual scene frames."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    update_project_status(project_id, "describing_scenes")
    try:
        result = describe_project_frames(project_directory)
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        update_project_status(project_id, "failed")
        logger.exception("Gemini scene description failed")
        raise HTTPException(status_code=502, detail="Gemini scene description failed.") from error
    return {"project_id": project_id, **result}


@router.post("/{project_id}/store-scene-embeddings")
def store_scene_embeddings(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Persist Gemini embeddings for the project's saved scene descriptions."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    update_project_status(project_id, "embedding")
    try:
        result = store_project_scene_embeddings(project_id, project_directory)
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        update_project_status(project_id, "failed")
        logger.exception("Scene embedding storage failed")
        raise HTTPException(status_code=502, detail="Scene embedding storage failed.") from error
    return {"project_id": project_id, **result}


@router.post("/{project_id}/match-script-beats")
def match_script_beats(project_id: str, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    """Match every script beat to its nearest stored video scene."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    update_project_status(project_id, "matching")
    try:
        matches = match_script_beats_to_scenes(project_id, project_directory)
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        update_project_status(project_id, "failed")
        logger.exception("Semantic scene matching failed")
        raise HTTPException(status_code=502, detail="Semantic scene matching failed.") from error
    return {
        "project_id": project_id,
        "beat_count": len(matches),
        "matches": matches,
    }


@router.post("/{project_id}/prepare-rough-cut")
def prepare_rough_cut(
    project_id: str, request: RoughCutSelectionRequest, user: dict[str, object] = Depends(get_current_user)
) -> dict[str, object]:
    """Prepare source-video selections from existing semantic match results."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    try:
        plan = create_rough_cut_selection_plan(
            project_directory,
            [match.model_dump() for match in request.matches],
        )
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        update_project_status(project_id, "failed")
        logger.exception("Rough-cut selection planning failed")
        raise HTTPException(status_code=502, detail="Rough-cut selection planning failed.") from error

    return {
        "project_id": project_id,
        "selection_count": len(plan),
        "selections": plan,
    }


@router.post("/{project_id}/render-rough-cut")
def render_project_rough_cut(
    project_id: str, request: RoughCutRenderRequest, user: dict[str, object] = Depends(get_current_user)
) -> dict[str, object]:
    """Render a new MP4 from an existing rough-cut selection plan."""
    project_directory = get_project_directory(project_id, int(user["id"]))
    update_project_status(project_id, "rendering")
    with connection() as db:
        template = db.execute("""SELECT t.output_width, t.output_height FROM projects p
                                 LEFT JOIN templates t ON t.id=p.template_id WHERE p.id=? AND p.user_id=?""",
                              (project_id, user["id"])).fetchone()
    try:
        result = render_rough_cut(
            project_id,
            project_directory,
            [selection.model_dump() for selection in request.selections],
            output_width=template["output_width"] if template and template["output_width"] else 1024,
            output_height=template["output_height"] if template and template["output_height"] else 576,
        )
    except ValueError as error:
        update_project_status(project_id, "failed")
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        update_project_status(project_id, "failed")
        logger.exception("Rough-cut rendering failed")
        raise HTTPException(status_code=500, detail=str(error)) from error

    with connection() as db:
        db.execute("""UPDATE projects
                      SET status='completed', output_video_path=?, output_duration_seconds=?, output_file_size_bytes=?,
                          updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                   (result["output_video_path"], result["duration_seconds"], result["file_size_bytes"], project_id))
    return {"project_id": project_id, **result}
