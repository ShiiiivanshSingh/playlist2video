"""
converter.py
------------
All the "heavy lifting" for turning an audio file + a static image into
a 1080p H.264/AAC MP4. No GUI code lives here on purpose, so it can be
reused from a script or tested independently of Tkinter.

Pipeline:
    1. get_media_duration()      -> ask ffprobe how long the audio is
    2. prepare_background_image() -> Pillow: scale + center-crop to 1920x1080
    3. build_ffmpeg_cmd()        -> assemble the ffmpeg command line
    4. run_ffmpeg_with_progress() -> run it, streaming progress back to caller
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image

TARGET_SIZE = (1920, 1080)  # Full HD, fixed per the spec


# --------------------------------------------------------------------------- #
# Duration lookup
# --------------------------------------------------------------------------- #
def get_media_duration(path: str) -> float:
    """Return the duration (in seconds) of an audio/video file via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        creationflags=_no_window_flag(),
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


# --------------------------------------------------------------------------- #
# Image preparation (scale + center-crop, no black bars)
# --------------------------------------------------------------------------- #
def prepare_background_image(image_path: str, output_path: str,
                              target_size: tuple[int, int] = TARGET_SIZE) -> str:
    """
    Scale the source image so it fully covers `target_size`, then
    center-crop the overflow. This guarantees a full-bleed 1920x1080
    frame with no letterboxing/pillarboxing, regardless of the source
    image's aspect ratio.
    """
    target_w, target_h = target_size

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        src_w, src_h = img.size

        src_ratio = src_w / src_h
        target_ratio = target_w / target_h

        if src_ratio > target_ratio:
            # Source is relatively wider than target -> match height, crop width.
            new_h = target_h
            new_w = max(target_w, round(new_h * src_ratio))
        else:
            # Source is relatively taller (or equal) -> match width, crop height.
            new_w = target_w
            new_h = max(target_h, round(new_w / src_ratio))

        img = img.resize((new_w, new_h), Image.LANCZOS)

        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))

        img.save(output_path, format="JPEG", quality=95)

    return output_path


# --------------------------------------------------------------------------- #
# ffmpeg command construction
# --------------------------------------------------------------------------- #
def build_ffmpeg_cmd(image_path: str, audio_path: str, output_path: str,
                      duration: float, video_bitrate: str = "8M",
                      audio_bitrate: str = "192k") -> list[str]:
    """
    Build the ffmpeg argument list.

    - `-loop 1` on the image input makes it repeat as a still frame.
    - `-t duration` (duration == audio length) caps the video so it ends
      exactly when the audio does. `-shortest` is kept as a safety net.
    - `-progress pipe:1` makes ffmpeg emit machine-readable key=value
      progress lines on stdout, which we parse for the progress bar.
    - `-movflags +faststart` moves the moov atom to the front of the
      file so the MP4 starts playing before it's fully downloaded
      (useful for YouTube / web playback).
    """
    return [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-tune", "stillimage",
        "-b:v", video_bitrate,
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "48000",
        "-shortest",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        "-loglevel", "error",
        output_path,
    ]


# --------------------------------------------------------------------------- #
# Running ffmpeg with progress reporting
# --------------------------------------------------------------------------- #
_TIME_RE = re.compile(r"^out_time_ms=(\d+)$")


def run_ffmpeg_with_progress(cmd: list[str], total_duration: float,
                              progress_callback: Optional[Callable[[float], None]] = None,
                              cancel_flag: Optional[Callable[[], bool]] = None) -> None:
    """
    Run the given ffmpeg command, calling `progress_callback(fraction)`
    (fraction in [0.0, 1.0]) as it goes. Raises RuntimeError with
    ffmpeg's stderr output on failure.

    `cancel_flag`, if given, is polled each line; when it returns True
    the ffmpeg process is terminated and a RuntimeError("cancelled") is
    raised.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=_no_window_flag(),
    )

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_flag is not None and cancel_flag():
                process.terminate()
                raise RuntimeError("cancelled")

            line = line.strip()
            match = _TIME_RE.match(line)
            if match and total_duration > 0:
                current_seconds = int(match.group(1)) / 1_000_000
                fraction = max(0.0, min(current_seconds / total_duration, 1.0))
                if progress_callback:
                    progress_callback(fraction)
            elif line == "progress=end":
                if progress_callback:
                    progress_callback(1.0)
    finally:
        stderr_output = process.stderr.read() if process.stderr else ""
        process.wait()

    if process.returncode != 0:
        raise RuntimeError(stderr_output.strip() or "ffmpeg exited with an error.")


# --------------------------------------------------------------------------- #
# High-level orchestration
# --------------------------------------------------------------------------- #
@dataclass
class ExportResult:
    output_path: str
    duration: float


def export_video(image_path: str, audio_path: str, output_path: str,
                  progress_callback: Optional[Callable[[float], None]] = None,
                  cancel_flag: Optional[Callable[[], bool]] = None) -> ExportResult:
    """
    End-to-end: figure out audio duration, prepare the background image,
    run ffmpeg, clean up the temp image. Safe to call from a worker thread.
    """
    duration = get_media_duration(audio_path)

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="audio2video_") as tmp_dir:
        prepared_image = os.path.join(tmp_dir, "background.jpg")
        prepare_background_image(image_path, prepared_image, TARGET_SIZE)

        cmd = build_ffmpeg_cmd(prepared_image, audio_path, output_path, duration)
        run_ffmpeg_with_progress(cmd, duration, progress_callback, cancel_flag)

    return ExportResult(output_path=output_path, duration=duration)


def _no_window_flag() -> int:
    """On Windows, suppress the console window that subprocess would
    otherwise pop up. No-op elsewhere."""
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0
