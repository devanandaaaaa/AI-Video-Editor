import json
import os
from pathlib import Path

from google import genai
from google.genai import types


DESCRIPTION_MODEL = "models/gemini-3.8-flash"
DESCRIPTION_PROMPT = """Describe this video frame for semantic video search.
Write one concise factual sentence. Mention the main people, actions, objects,
setting, and camera-relevant event if visible. Do not speculate about things
outside the frame and do not add headings or bullet points."""


def describe_project_frames(project_directory: Path) -> dict[str, object]:
    """Use Gemini vision to describe every extracted JPEG frame in a project."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    frame_paths = sorted(project_directory.glob("frames/clip_*/*.jpg"))
    if not frame_paths:
        raise ValueError("No extracted frames found. Run extract-frames first.")

    client = genai.Client(api_key=api_key)
    scenes: list[dict[str, object]] = []
    for index, frame_path in enumerate(frame_paths, start=1):
        image_bytes = frame_path.read_bytes()
        response = client.models.generate_content(
            model=DESCRIPTION_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                DESCRIPTION_PROMPT,
            ],
        )
        description = (response.text or "").strip()
        if not description:
            description = "No visual description was returned for this frame."

        clip_name = frame_path.parent.name
        frame_number = int(frame_path.stem.removeprefix("frame_"))
        scenes.append(
            {
                "scene_number": index,
                "clip_name": clip_name,
                "frame_number": frame_number,
                "image_path": str(frame_path.relative_to(project_directory)).replace("\\", "/"),
                "description": description,
            }
        )

    result = {"model": DESCRIPTION_MODEL, "scene_count": len(scenes), "scenes": scenes}
    (project_directory / "scene_descriptions.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
