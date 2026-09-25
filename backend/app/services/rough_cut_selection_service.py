"""Prepare rough-cut source segments from already matched script beats."""

from pathlib import Path

from app.services.frame_extraction_service import FRAME_INTERVAL_SECONDS, get_video_duration_seconds


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}


def find_source_video(project_directory: Path, clip_name: str) -> Path:
    """Find the uploaded raw video that belongs to a stored clip stem."""
    candidates = [
        project_directory / f"{clip_name}{extension}"
        for extension in ALLOWED_VIDEO_EXTENSIONS
        if (project_directory / f"{clip_name}{extension}").is_file()
    ]
    if len(candidates) != 1:
        raise ValueError(f"Could not find exactly one source video for {clip_name}.")
    return candidates[0]


def create_rough_cut_selection_plan(
    project_directory: Path, matches: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Map matched scenes to full-clip MVP segments without trimming any media."""
    if not matches:
        raise ValueError("Provide at least one semantic match to prepare a selection plan.")

    plan: list[dict[str, object]] = []
    for match in matches:
        clip_name = match["clip_name"]
        frame_number = match["frame_number"]
        if not isinstance(clip_name, str) or not isinstance(frame_number, int):
            raise ValueError("Each match must include a clip name and numeric frame number.")

        source_video = find_source_video(project_directory, clip_name)
        duration = get_video_duration_seconds(source_video)
        matched_timestamp = (frame_number - 1) * FRAME_INTERVAL_SECONDS

        plan.append(
            {
                "beat_number": match["beat_number"],
                "beat_text": match["beat_text"],
                "matched_scene_number": match["matched_scene_number"],
                "clip_name": clip_name,
                "source_video_path": str(
                    source_video.relative_to(project_directory.parents[1])
                ).replace("\\", "/"),
                "matched_timestamp_seconds": float(matched_timestamp),
                "source_clip_duration": round(duration, 3),
                "segment_start_seconds": 0.0,
                "segment_end_seconds": round(duration, 3),
            }
        )

    return plan
