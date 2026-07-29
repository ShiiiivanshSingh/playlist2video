"""
utils.py
--------
Small shared helpers: file-type validation, ffmpeg presence check,
and a couple of formatting helpers used by the GUI.
"""

import os
import shutil

# File types we accept in the "select audio" / "select image" dialogs.
SUPPORTED_AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma")
SUPPORTED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def check_ffmpeg_installed() -> bool:
    """Return True if both ffmpeg and ffprobe are on PATH."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def validate_audio_file(path: str) -> str | None:
    """Return an error message if the audio file is invalid, else None."""
    if not path:
        return "Please select an audio file."
    if not os.path.isfile(path):
        return f"Audio file not found:\n{path}"
    if not path.lower().endswith(SUPPORTED_AUDIO_EXTS):
        return (
            "Unsupported audio format. Supported types:\n"
            + ", ".join(SUPPORTED_AUDIO_EXTS)
        )
    return None


def validate_image_file(path: str) -> str | None:
    """Return an error message if the image file is invalid, else None."""
    if not path:
        return "Please select a background image."
    if not os.path.isfile(path):
        return f"Image file not found:\n{path}"
    if not path.lower().endswith(SUPPORTED_IMAGE_EXTS):
        return (
            "Unsupported image format. Supported types:\n"
            + ", ".join(SUPPORTED_IMAGE_EXTS)
        )
    return None


def validate_output_path(path: str) -> str | None:
    """Return an error message if the output path is invalid, else None."""
    if not path:
        return "Please choose an output location."
    if not path.lower().endswith(".mp4"):
        return "Output file must end with .mp4"
    out_dir = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        return f"Could not create output directory:\n{exc}"
    return None


def format_seconds(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS or M:SS."""
    if seconds is None or seconds < 0:
        seconds = 0
    seconds = int(round(seconds))
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hrs:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"
