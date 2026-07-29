# 🎵→🎬 Audio Grabber + Video Maker

Download any song, YouTube playlist, or Spotify tracklist as high-quality audio — and optionally turn it into a **1920×1080 MP4 video** with a background image. All in one workflow, no switching between tools.

---
<div align="center">


<img src="https://github.com/user-attachments/assets/4f78f8bf-6d32-4293-8399-3c39e494c3a6" alt="Logo" width="500" />

# Final Product!

<img src="https://github.com/user-attachments/assets/d7463f9e-e24e-4440-8f64-119856bb979c" alt="Final Product" width="700" />

</div>
## Features

| | Audio mode | Video mode |
|---|---|---|
| Single song (search or URL) | ✅ MP3 / FLAC | ✅ 1080p MP4 |
| YouTube playlist | ✅ merged file | ✅ 1080p MP4 |
| Spotify / JSON tracklist | ✅ merged file | ✅ 1080p MP4 |
| Interface | Web UI + CLI | Web UI + CLI |

---

## Requirements

### System dependencies
- **Python 3.10+**
- **ffmpeg** (must be on your PATH)
  - macOS: `brew install ffmpeg`
  - Windows: `winget install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

### Python packages
```bash
pip install -r requirements.txt
```

---

## Quick Start — Web UI

```bash
python3 server.py
```

Open **http://127.0.0.1:8888** in your browser.

### Audio-only
1. Type a song name, paste a YouTube URL or playlist link
2. Choose MP3 or FLAC
3. Hit **go**

### Audio → Video (1080p MP4)
1. Flip the **"audio only"** toggle → it becomes **"make video (1080p mp4)"**
2. Drop or browse a background image (PNG / JPG / WEBP / BMP)
3. Enter your song / playlist / tracklist as usual
4. Hit **go** — the app downloads the audio, then encodes the MP4 automatically
5. The intermediate audio file is deleted; you keep only the `.mp4`

### Tracklist tab
Paste lines in `Artist - Song Title` format, or drop / paste a JSON file like `Sample Data.json`:
```json
[
  { "song": "Blinding Lights", "artist": "The Weeknd" },
  { "song": "Pumped Up Kicks",  "artist": "Foster The People" }
]
```

---

## Quick Start — CLI

### Single song
```bash
# Audio only
python3 yt_audio_downloader.py "Blinding Lights The Weeknd"
python3 yt_audio_downloader.py "Blinding Lights The Weeknd" --format flac

# → 1080p MP4
python3 yt_audio_downloader.py "Blinding Lights The Weeknd" \
  --make-video --image /path/to/background.jpg
```

### YouTube playlist
```bash
# Audio only — merges all tracks into one file
python3 yt_audio_downloader.py "https://youtube.com/playlist?list=..."

# → 1080p MP4
python3 yt_audio_downloader.py "https://youtube.com/playlist?list=..." \
  --make-video --image /path/to/bg.png
```

### JSON tracklist
```bash
# Uses YouTube to find each track by name + artist, merges them in order
python3 yt_audio_downloader.py --tracklist "Sample Data.json" --name "My Mix"

# → 1080p MP4
python3 yt_audio_downloader.py --tracklist "Sample Data.json" \
  --name "My Mix" --make-video --image /path/to/bg.jpg
```

### All CLI flags
```
positional:
  query             Song name, YouTube URL, or playlist link

optional:
  --format          mp3 (default) or flac
  --tracklist PATH  Path to JSON tracklist file
  --name TEXT       Output file name (defaults to song/playlist title)
  --output-dir DIR  Save folder (defaults to ~/Downloads)
  --make-video      Produce a 1920×1080 MP4 instead of audio-only
  --image PATH      Background image path (required with --make-video)
```

---

## File Structure

```
master repo/
├── server.py               # Flask web server — run this to use the web UI
├── core.py                 # Audio download + playlist pipeline (yt-dlp)
├── converter.py            # Image + audio → 1080p MP4 (ffmpeg + Pillow)
├── yt_audio_downloader.py  # CLI entry point
├── static/
│   └── index.html          # Single-page web UI
├── Sample Data.json        # Example tracklist (67 songs)
├── requirements.txt        # Python dependencies
└── beta build/             # Original separate tools (kept for reference)
    ├── audio gen/          #   Original audio-only web app
    └── video tools/        #   Original desktop GUI (CustomTkinter)
```

---

## Output Format Details

| Setting | Detail |
|---|---|
| MP3 bitrate | 320 kbps (CBR) |
| FLAC | Lossless, 44100 Hz stereo |
| Video resolution | 1920 × 1080 (Full HD) |
| Video codec | H.264 (`libx264`), preset `medium` |
| Video bitrate | 8 Mbps |
| Audio in video | AAC, 192 kbps, 48000 Hz |
| Background image | Auto scale + center-crop, no letterboxing |

---

## Notes

- **Spotify links** are not supported directly (Spotify blocks the API for free tier). Use the tracklist tab / `--tracklist` flag with a JSON file instead.
- The server runs locally on `127.0.0.1:8888` — it is **not** meant to be exposed to the internet.
- For long playlists, the video encoding step can take several minutes. The progress bar in the web UI and the `Video encoding: X%` output in the CLI show live progress.
