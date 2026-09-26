"""Create and persist Gemini embeddings for saved scene descriptions."""

import json
import os
from pathlib import Path

import chromadb
from google import genai
from google.genai import types
from app.config import DATA_DIRECTORY


EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 768
CHROMA_DIRECTORY = DATA_DIRECTORY / "chroma_data"


def _collection_name(project_id: str) -> str:
    """Return a valid, project-specific ChromaDB collection name."""
    return f"project_{project_id.replace('-', '_')}_scenes"


def get_project_scene_collection(project_id: str):
    """Open the existing persistent scene collection for one project."""
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIRECTORY))
    try:
        return chroma_client.get_collection(name=_collection_name(project_id))
    except ValueError as error:
        raise ValueError("No stored scene embeddings found. Run store-scene-embeddings first.") from error


def format_scene_document(description: str, clip_name: str, frame_number: int) -> str:
    """Format scene text as a searchable document for Gemini Embedding 2."""
    return f"title: video scene {clip_name}, frame {frame_number} | text: {description}"


def store_project_scene_embeddings(project_id: str, project_directory: Path) -> dict[str, object]:
    """Embed saved scene descriptions and persist them in this project's collection."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    descriptions_path = project_directory / "scene_descriptions.json"
    if not descriptions_path.is_file():
        raise ValueError("No scene descriptions found. Run describe-scenes first.")

    try:
        saved_descriptions = json.loads(descriptions_path.read_text(encoding="utf-8"))
        scenes = saved_descriptions["scenes"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("The saved scene descriptions file is invalid.") from error

    if not scenes:
        raise ValueError("No scene descriptions are available to embed.")

    client = genai.Client(api_key=api_key)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIRECTORY))
    collection = chroma_client.get_or_create_collection(
        name=_collection_name(project_id),
        metadata={"project_id": project_id, "embedding_model": EMBEDDING_MODEL},
    )

    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict[str, str | int]] = []

    for scene in scenes:
        description = scene.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Every saved scene must contain a description.")

        scene_number = scene.get("scene_number")
        frame_number = scene.get("frame_number")
        clip_name = scene.get("clip_name")
        image_path = scene.get("image_path")
        if not isinstance(scene_number, int) or not isinstance(frame_number, int):
            raise ValueError("Every saved scene must contain numeric scene and frame numbers.")
        if not isinstance(clip_name, str) or not isinstance(image_path, str):
            raise ValueError("Every saved scene must contain clip and image paths.")

        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=format_scene_document(description, clip_name, frame_number),
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("Gemini did not return an embedding for a scene description.")

        embedding = list(response.embeddings[0].values)
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError("Gemini returned an embedding with an unexpected size.")

        ids.append(f"scene_{scene_number}")
        embeddings.append(embedding)
        documents.append(description)
        metadatas.append(
            {
                "project_id": project_id,
                "clip_name": clip_name,
                "scene_number": scene_number,
                "frame_number": frame_number,
                "image_path": image_path,
                "description": description,
            }
        )

    # upsert makes a retry safe: records with the same scene number are updated.
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    return {
        "collection_name": collection.name,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "stored_scene_count": len(ids),
        "collection_record_count": collection.count(),
        "storage_path": str(CHROMA_DIRECTORY),
    }
