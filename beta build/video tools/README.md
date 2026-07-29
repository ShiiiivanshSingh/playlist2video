# Audio to Video Converter (1080p)

A small desktop app that turns an audio file + a static background image
into a Full HD (1920x1080) MP4, sized to a specific need: quick YouTube
uploads for audio-only content (podcasts, music, etc.).

## Features

- Pick an audio file (MP3, WAV, FLAC, M4A, AAC, OGG, WMA)
- Pick a background image (PNG, JPG/JPEG, WEBP, BMP)
- Image is scaled + center-cropped to exactly 1920x1080 with no black bars,
  regardless of its original aspect ratio
- Output video duration always matches the audio duration exactly
- H.264 video + AAC audio in an MP4 container, with `+faststart` for
  smooth web/YouTube playback
- Progress bar + estimated time remaining while exporting
- Rendering runs on a background thread, so the UI never freezes
- Input validation with clear error dialogs
- Output directory is created automatically if it doesn't exist

## Requirements

- Python 3.10+
- **FFmpeg** installed and available on your system `PATH` (this app shells
  out to `ffmpeg`/`ffprobe` -- it is not bundled).
  - Windows: download from https://ffmpeg.org/download.html, or
    `winget install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Linux (Debian/Ubuntu): `sudo apt install ffmpeg`

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Project layout

```
main.py         Entry point
gui.py          CustomTkinter (falls back to plain Tkinter) UI
converter.py    ffprobe/ffmpeg/Pillow pipeline (no GUI code)
utils.py        Validation + small formatting helpers
requirements.txt
```

## Notes

- If `customtkinter` isn't installed, the app automatically falls back to
  plain Tkinter/ttk widgets so it still runs -- you just lose the themed
  look.
- Video bitrate defaults to 8 Mbps (`-b:v 8M`), a good balance of quality
  and file size for a static-image 1080p video destined for YouTube. Edit
  `build_ffmpeg_cmd()` in `converter.py` if you want to change it.
- Frame rate is fixed at 30fps for a still-image video; this keeps file
  size down without any visible quality loss since nothing is moving.
