import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

import core
from converter import export_video

app = Flask(__name__, static_folder="static", static_url_path="")

jobs = {}

# Temp dir for uploaded images — cleaned up per-job
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "audio_dl_images"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/downloads_folder")
def api_downloads_folder():
    return jsonify({"path": str(core.get_downloads_folder())})


# ---------------------------------------------------------------------- #
# Image upload
# ---------------------------------------------------------------------- #
@app.route("/api/upload_image", methods=["POST"])
def api_upload_image():
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "No image file provided."}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"Unsupported image type '{ext}'. Allowed: {', '.join(ALLOWED_IMAGE_EXTS)}"}), 400
    image_id = uuid.uuid4().hex
    dest = _UPLOAD_DIR / f"{image_id}{ext}"
    f.save(str(dest))
    return jsonify({"image_id": image_id, "filename": f.filename})


def _resolve_image_path(image_id):
    """Return the saved image Path for image_id, or None if not found."""
    if not image_id:
        return None
    for ext in ALLOWED_IMAGE_EXTS:
        p = _UPLOAD_DIR / f"{image_id}{ext}"
        if p.exists():
            return p
    return None


def new_job():
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"log": [], "done": False, "error": None, "file": None, "tracklist": None, "cancelled": False}
    return job_id


def start_job(target, job_id, args):
    thread = threading.Thread(target=target, args=(job_id, *args), daemon=True)
    thread.start()


@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    audio_format = data.get("format") or core.DEFAULT_FORMAT
    if audio_format not in core.SUPPORTED_FORMATS:
        audio_format = core.DEFAULT_FORMAT
    output_name = (data.get("name") or "").strip() or None
    output_dir = (data.get("output_dir") or "").strip() or None
    make_video = bool(data.get("make_video"))
    image_id = (data.get("image_id") or "").strip() or None

    if not query:
        return jsonify({"error": "No input provided."}), 400
    if not core.check_ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this machine."}), 400
    if core.is_spotify_url(query):
        return jsonify({"error": "Use the paste-a-tracklist option below for Spotify playlists."}), 400
    if make_video and not _resolve_image_path(image_id):
        return jsonify({"error": "Video mode requires a background image. Please upload one first."}), 400

    job_id = new_job()
    start_job(run_query_job, job_id, (query, audio_format, output_name, output_dir, make_video, image_id))
    return jsonify({"job_id": job_id})


@app.route("/api/process_tracklist", methods=["POST"])
def api_process_tracklist():
    data = request.get_json(force=True, silent=True) or {}
    raw_tracklist = data.get("tracklist")
    playlist_name = (data.get("name") or "Pasted Playlist").strip() or "Pasted Playlist"
    audio_format = data.get("format") or core.DEFAULT_FORMAT
    if audio_format not in core.SUPPORTED_FORMATS:
        audio_format = core.DEFAULT_FORMAT
    output_dir = (data.get("output_dir") or "").strip() or None
    make_video = bool(data.get("make_video"))
    image_id = (data.get("image_id") or "").strip() or None

    if not core.check_ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this machine."}), 400
    if make_video and not _resolve_image_path(image_id):
        return jsonify({"error": "Video mode requires a background image. Please upload one first."}), 400
    try:
        tracks = core.normalize_tracklist(raw_tracklist)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    job_id = new_job()
    start_job(run_tracklist_job, job_id, (tracks, playlist_name, audio_format, output_dir, make_video, image_id))
    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job."}), 404
    job["cancelled"] = True
    return jsonify({"ok": True})


def _maybe_make_video(job, audio_path, image_id, report):
    """
    If image_id is set, convert audio_path to a 1080p MP4 beside it.
    Returns the final output Path (MP4 if converted, original audio otherwise).
    """
    image_path = _resolve_image_path(image_id)
    if not image_path:
        return audio_path

    video_path = audio_path.with_suffix(".mp4")
    report("Creating video (this may take a while for long tracks)...")

    def on_progress(fraction):
        pct = int(fraction * 100)
        report(f"Video encoding: {pct}%")

    export_video(
        image_path=str(image_path),
        audio_path=str(audio_path),
        output_path=str(video_path),
        progress_callback=on_progress,
        cancel_flag=lambda: job["cancelled"],
    )

    # Remove the intermediate audio file — keep only the MP4
    try:
        audio_path.unlink(missing_ok=True)
    except Exception:
        pass
    # Clean up the uploaded image
    try:
        image_path.unlink(missing_ok=True)
    except Exception:
        pass

    return video_path


def run_query_job(job_id, query, audio_format, output_name, output_dir, make_video=False, image_id=None):
    job = jobs[job_id]
    report = job["log"].append
    try:
        downloads_dir = core.resolve_output_dir(output_dir)
    except Exception as e:
        job["error"] = f"Could not use that output folder: {e}"
        job["done"] = True
        return
    temp_dir = Path(tempfile.mkdtemp(prefix="audio_dl_"))
    try:
        if core.is_youtube_playlist_url(query):
            audio_path = core.process_youtube_playlist(
                query, audio_format, downloads_dir, temp_dir, report,
                output_name=output_name, should_cancel=lambda: job["cancelled"],
            )
        else:
            audio_path = core.process_song(query, audio_format, downloads_dir, temp_dir, report, output_name=output_name)

        if make_video and image_id:
            final_path = _maybe_make_video(job, audio_path, image_id, report)
        else:
            final_path = audio_path

        job["file"] = str(final_path)
        report(f"Saved: {final_path}")
    except Exception as e:
        job["error"] = str(e)
        report(f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        job["done"] = True


def run_tracklist_job(job_id, tracks, playlist_name, audio_format, output_dir, make_video=False, image_id=None):
    job = jobs[job_id]
    report = job["log"].append
    try:
        downloads_dir = core.resolve_output_dir(output_dir)
    except Exception as e:
        job["error"] = f"Could not use that output folder: {e}"
        job["done"] = True
        return
    temp_dir = Path(tempfile.mkdtemp(prefix="audio_dl_"))
    try:
        audio_path, tracklist = core.process_tracklist(
            tracks, playlist_name, audio_format, downloads_dir, temp_dir, report,
            should_cancel=lambda: job["cancelled"],
        )

        if make_video and image_id:
            final_path = _maybe_make_video(job, audio_path, image_id, report)
        else:
            final_path = audio_path

        job["file"] = str(final_path)
        job["tracklist"] = tracklist
        report(f"Saved: {final_path}")
    except Exception as e:
        job["error"] = str(e)
        report(f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        job["done"] = True


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job."}), 404
    return jsonify(job)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8888, threaded=True)
