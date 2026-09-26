"""Gemini-based voiceover understanding for the audio-first project workflow."""
import json
import os
import re
import subprocess
from pathlib import Path

from google import genai
from google.genai import types


AUDIO_MODEL = "models/gemini-3.8-flash"
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 30 * 60
SUPPORTED_AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".webm": "audio/webm",
}
VOICEOVER_PROMPT = """Listen carefully to this voiceover and return JSON only.
Return `original_language` (language name), `transcript` (faithful spoken-language transcript),
and `normalized_text` (English semantic normalization; translate only where needed without changing meaning).
Return `beats` as a chronological array derived only from the narration. Every beat must contain:
`order` (integer), `normalized_narration` (concise English narration), `semantic_meaning`
(the narrative idea), `visual_concepts` (an array of concrete visual search concepts), and
`narrative_relevance` (why the beat matters to the story). Do not invent events, visual facts,
names, or claims that are not in the audio. Return an empty beats array if there is no meaningful narration."""


def _probe_audio(path: Path) -> float:
    """Validate decodability and return duration without trusting the file extension."""
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        duration = float(completed.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as error:
        raise ValueError("The voiceover file is corrupted or cannot be decoded.") from error
    if duration <= 0:
        raise ValueError("The voiceover file has no playable audio.")
    if duration > MAX_AUDIO_DURATION_SECONDS:
        raise ValueError("The voiceover is longer than the current 30-minute processing limit.")
    return duration


def _parse_json(response_text: str) -> dict[str, object]:
    candidate = response_text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini returned an unreadable voiceover analysis.") from error
    if not isinstance(data, dict):
        raise ValueError("Gemini returned an invalid voiceover analysis.")
    return data


def analyze_voiceover(project_directory: Path, audio_file_name: str) -> dict[str, object]:
    """Create persistent faithful transcript, normalized text, and semantic story beats."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is not configured.")
    audio_path = project_directory / audio_file_name
    if not audio_path.is_file():
        raise ValueError("The uploaded voiceover file was not found.")
    if audio_path.stat().st_size > MAX_AUDIO_BYTES:
        raise ValueError("The voiceover exceeds the 20 MB processing limit.")
    mime_type = SUPPORTED_AUDIO_MIME_TYPES.get(audio_path.suffix.lower())
    if not mime_type:
        raise ValueError("This voiceover format is not supported.")
    duration = _probe_audio(audio_path)

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=AUDIO_MODEL,
            contents=[types.Part.from_bytes(data=audio_path.read_bytes(), mime_type=mime_type), VOICEOVER_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as error:
        raise RuntimeError("Gemini could not understand the voiceover. Please try again.") from error
    data = _parse_json(response.text or "")
    transcript = data.get("transcript")
    normalized_text = data.get("normalized_text")
    raw_beats = data.get("beats")
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("Gemini returned an empty voiceover transcription.")
    if not isinstance(normalized_text, str) or not normalized_text.strip():
        raise ValueError("Gemini did not return normalized voiceover text.")
    if not isinstance(raw_beats, list):
        raise ValueError("Gemini did not return story beats.")
    beats: list[dict[str, object]] = []
    for item in raw_beats:
        if not isinstance(item, dict):
            continue
        narration = item.get("normalized_narration") or item.get("text")
        meaning = item.get("semantic_meaning")
        relevance = item.get("narrative_relevance")
        concepts = item.get("visual_concepts")
        if not isinstance(narration, str) or not narration.strip():
            continue
        if not isinstance(meaning, str) or not meaning.strip():
            continue
        if not isinstance(relevance, str) or not relevance.strip():
            continue
        if not isinstance(concepts, list) or not all(isinstance(concept, str) and concept.strip() for concept in concepts):
            continue
        order = len(beats) + 1
        beats.append({
            "order": order,
            "beat_number": order,
            "text": narration.strip(),
            "normalized_narration": narration.strip(),
            "semantic_meaning": meaning.strip(),
            "visual_concepts": [concept.strip() for concept in concepts],
            "narrative_relevance": relevance.strip(),
        })
    if not beats:
        raise ValueError("No meaningful story beats could be extracted from this voiceover.")
    result = {
        "model": AUDIO_MODEL, "audio_file": audio_file_name, "duration_seconds": round(duration, 3),
        "original_language": data.get("original_language") if isinstance(data.get("original_language"), str) else "Unknown",
        "transcript": transcript.strip(), "normalized_text": normalized_text.strip(), "beat_count": len(beats), "beats": beats,
    }
    (project_directory / "voiceover_analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def get_voiceover_beats(project_directory: Path) -> list[dict[str, object]]:
    path = project_directory / "voiceover_analysis.json"
    if not path.is_file():
        raise ValueError("Voiceover has not been understood yet. Run understand-voiceover first.")
    try:
        beats = json.loads(path.read_text(encoding="utf-8")).get("beats")
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError("Saved voiceover analysis is invalid.") from error
    if not isinstance(beats, list) or not beats:
        raise ValueError("No meaningful voiceover story beats are available.")
    return beats
