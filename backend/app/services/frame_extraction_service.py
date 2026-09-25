import json
import math
import subprocess
from pathlib import Path


FRAME_INTERVAL_SECONDS = 5
MAX_FRAMES_PER_CLIP = 12


def get_video_duration_seconds(video_path: Path) -> float:
    """Read a clip duration with FFprobe, which is included with FFmpeg."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if duration <= 0:
        raise ValueError("The video duration must be greater than zero.")
    return duration


def extract_project_frames(project_directory: Path) -> list[dict[str, object]]:
    """Create representative JPEG frames for every saved raw clip."""
    clips = sorted(project_directory.glob("clip_*"))
    if not clips:
        raise ValueError("This project has no uploaded video clips.")

    extracted_clips: list[dict[str, object]] = []
    for clip in clips:
        duration = get_video_duration_seconds(clip)
        timestamps = list(range(0, math.ceil(duration), FRAME_INTERVAL_SECONDS))
        timestamps = timestamps[:MAX_FRAMES_PER_CLIP] or [0]

        clip_frames_directory = project_directory / "frames" / clip.stem
        clip_frames_directory.mkdir(parents=True, exist_ok=True)
        frames: list[dict[str, object]] = []

        for frame_number, timestamp in enumerate(timestamps, start=1):
            frame_name = f"frame_{frame_number:03}.jpg"
            frame_path = clip_frames_directory / frame_name
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(clip),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                capture_output=True,
                check=True,
            )
            frames.append(
                {
                    "frame_number": frame_number,
                    "timestamp_seconds": timestamp,
                    "image_path": str(frame_path.relative_to(project_directory)).replace("\\", "/"),
                }
            )

        extracted_clips.append(
            {
                "clip_name": clip.name,
                "duration_seconds": round(duration, 2),
                "frames": frames,
            }
        )

    return extracted_clips
