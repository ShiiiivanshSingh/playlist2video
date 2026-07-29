import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

import core

app = Flask(__name__, static_folder="static", static_url_path="")

jobs = {}


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/downloads_folder")
def api_downloads_folder():
    return jsonify({"path": str(core.get_downloads_folder())})


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
    if not query:
        return jsonify({"error": "No input provided."}), 400
    if not core.check_ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this machine."}), 400
    if core.is_spotify_url(query):
        return jsonify({"error": "Use the paste-a-tracklist option below for Spotify playlists."}), 400

    job_id = new_job()
    start_job(run_query_job, job_id, (query, audio_format, output_name, output_dir))
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
    if not core.check_ffmpeg_available():
        return jsonify({"error": "ffmpeg is not installed on this machine."}), 400
    try:
        tracks = core.normalize_tracklist(raw_tracklist)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    job_id = new_job()
    start_job(run_tracklist_job, job_id, (tracks, playlist_name, audio_format, output_dir))
    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job."}), 404
    job["cancelled"] = True
    return jsonify({"ok": True})


def run_query_job(job_id, query, audio_format, output_name, output_dir):
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
            final_path = core.process_youtube_playlist(
                query, audio_format, downloads_dir, temp_dir, report,
                output_name=output_name, should_cancel=lambda: job["cancelled"],
            )
        else:
            final_path = core.process_song(query, audio_format, downloads_dir, temp_dir, report, output_name=output_name)
        job["file"] = str(final_path)
        report(f"Saved: {final_path}")
    except Exception as e:
        job["error"] = str(e)
        report(f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        job["done"] = True


def run_tracklist_job(job_id, tracks, playlist_name, audio_format, output_dir):
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
        final_path, tracklist = core.process_tracklist(
            tracks, playlist_name, audio_format, downloads_dir, temp_dir, report,
            should_cancel=lambda: job["cancelled"],
        )
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
