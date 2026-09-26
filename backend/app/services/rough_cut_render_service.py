"""Render a rough-cut MP4 from an existing rough-cut selection plan."""

import subprocess
from pathlib import Path
from uuid import uuid4

from app.services.frame_extraction_service import get_video_duration_seconds
from app.services.rough_cut_selection_service import find_source_video
from app.config import DATA_DIRECTORY


OUTPUT_WIDTH = 1024
OUTPUT_HEIGHT = 576
OUTPUT_FRAME_RATE = 30


def _validate_segment(
    project_directory: Path, selection: dict[str, object]
) -> tuple[Path, float, float]:
    """Validate one planned segment against its original uploaded video."""
    clip_name = selection["clip_name"]
    start = selection["segment_start_seconds"]
    end = selection["segment_end_seconds"]
    if not isinstance(clip_name, str) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError("Each selection needs a clip name and numeric start/end times.")
    if start < 0 or end <= start:
        raise ValueError("Each segment must have a non-negative start time before its end time.")

    source_video = find_source_video(project_directory, clip_name)
    source_duration = get_video_duration_seconds(source_video)
    if end > source_duration + 0.05:
        raise ValueError(f"The selected end time exceeds the duration of {clip_name}.")
    return source_video, float(start), min(float(end), source_duration)


def render_rough_cut(
    project_id: str, project_directory: Path, selections: list[dict[str, object]],
    output_width: int = OUTPUT_WIDTH, output_height: int = OUTPUT_HEIGHT,
) -> dict[str, object]:
    """Trim planned source ranges and concatenate them into a new MP4 output."""
    if not selections:
        raise ValueError("Provide at least one selection to render a rough cut.")
    if output_width <= 0 or output_height <= 0:
        raise ValueError("The selected template has invalid output dimensions.")

    validated_segments = [_validate_segment(project_directory, selection) for selection in selections]
    output_directory = DATA_DIRECTORY / "outputs" / project_id
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"rough_cut_{uuid4().hex}.mp4"

    voiceover_paths = sorted(project_directory.glob("voiceover.*"))
    voiceover_path = voiceover_paths[0] if voiceover_paths else None
    voiceover_duration = get_video_duration_seconds(voiceover_path) if voiceover_path else 0.0
    command = ["ffmpeg", "-y"]
    for source_video, start, end in validated_segments:
        command.extend(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(source_video)])
    if voiceover_path:
        command.extend(["-i", str(voiceover_path)])

    filters: list[str] = []
    for index in range(len(validated_segments)):
        filters.append(
            f"[{index}:v]setpts=PTS-STARTPTS,"
            f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={OUTPUT_FRAME_RATE}[video{index}]"
        )
    video_inputs = "".join(f"[video{index}]" for index in range(len(validated_segments)))
    filters.append(f"{video_inputs}concat=n={len(validated_segments)}:v=1:a=0[roughcut]")
    if voiceover_path:
        # Raw clip audio is intentionally discarded; the user's original voiceover is primary.
        filters.append(f"[roughcut]tpad=stop_mode=clone:stop_duration={voiceover_duration:.3f}[finalvideo]")

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[finalvideo]" if voiceover_path else "[roughcut]",
        ]
    )
    if voiceover_path:
        command.extend([
            "-map", f"{len(validated_segments)}:a:0", "-t", f"{voiceover_duration:.3f}",
            "-c:a", "aac", "-b:a", "192k",
        ])
    else:
        command.extend(["-an"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError("FFmpeg could not render the rough-cut MP4.") from error

    return {
        "output_video_path": str(output_path.relative_to(output_directory.parent)).replace("\\", "/"),
        "segment_count": len(validated_segments),
        "duration_seconds": round(get_video_duration_seconds(output_path), 3),
        "file_size_bytes": output_path.stat().st_size,
        "video_width": output_width,
        "video_height": output_height,
        "frame_rate": OUTPUT_FRAME_RATE,
    }
