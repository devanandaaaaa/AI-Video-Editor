"""Match script beats to the closest existing video scenes."""

import os
from pathlib import Path

from google import genai
from google.genai import types

from app.services.embedding_service import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    get_project_scene_collection,
)
from app.services.script_service import split_script_into_beats


def match_script_beats_to_scenes(project_id: str, project_directory: Path) -> list[dict[str, object]]:
    """Return the nearest stored scene for every beat in the project's script."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    script_path = project_directory / "script.txt"
    script_text = script_path.read_text(encoding="utf-8-sig").strip()
    if not script_text:
        raise ValueError("The uploaded script is empty.")

    beats = split_script_into_beats(script_text)
    collection = get_project_scene_collection(project_id)
    if collection.count() == 0:
        raise ValueError("No stored scene embeddings found. Run store-scene-embeddings first.")

    client = genai.Client(api_key=api_key)
    matches: list[dict[str, object]] = []
    for beat in beats:
        beat_text = beat["text"]
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=f"task: search result | query: {beat_text}",
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("Gemini did not return an embedding for a script beat.")

        beat_embedding = list(response.embeddings[0].values)
        if len(beat_embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError("Gemini returned an embedding with an unexpected size.")

        result = collection.query(
            query_embeddings=[beat_embedding],
            n_results=1,
            include=["metadatas", "distances"],
        )
        if not result["metadatas"] or not result["metadatas"][0]:
            raise ValueError("ChromaDB did not return a scene match.")

        metadata = result["metadatas"][0][0]
        distance = result["distances"][0][0]
        matches.append(
            {
                "beat_number": beat["beat_number"],
                "beat_text": beat_text,
                "matched_scene_number": metadata["scene_number"],
                "clip_name": metadata["clip_name"],
                "frame_number": metadata["frame_number"],
                "image_path": metadata["image_path"],
                "scene_description": metadata["description"],
                "distance": distance,
            }
        )

    return matches
