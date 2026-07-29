import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

SUPPORTED_FORMATS = ("mp3", "flac")
DEFAULT_FORMAT = "mp3"
MP3_BITRATE = "320k"
SAMPLE_RATE = "44100"

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"


def check_ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def get_downloads_folder():
    home = Path.home()
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            value, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            winreg.CloseKey(key)
            return Path(value)
        except Exception:
            return home / "Downloads"
    return home / "Downloads"


def sanitize_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "audio_output"


def resolve_output_dir(custom_path=None):
    if custom_path:
        resolved = Path(custom_path).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
    downloads_dir = get_downloads_folder()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir


def is_url(text):
    return text.strip().lower().startswith(("http://", "https://"))


def is_youtube_playlist_url(text):
    lowered = text.strip().lower()
    return is_url(text) and ("list=" in lowered or "/playlist" in lowered) and "spotify" not in lowered


def is_spotify_url(text):
    lowered = text.strip().lower()
    return "open.spotify.com/playlist" in lowered or lowered.startswith("spotify:playlist:")


def extract_spotify_playlist_id(text):
    match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", text)
    if not match:
        raise RuntimeError("Could not find a playlist ID in that Spotify link.")
    return match.group(1)


def run_ffmpeg(args):
    result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def convert_to_wav(input_path, output_path):
    run_ffmpeg(["-i", str(input_path), "-ar", SAMPLE_RATE, "-ac", "2", str(output_path)])


def encode_final(input_path, output_path, audio_format):
    if audio_format == "mp3":
        run_ffmpeg(["-i", str(input_path), "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, str(output_path)])
    else:
        run_ffmpeg(["-i", str(input_path), "-codec:a", "flac", str(output_path)])


def concat_wavs(wav_paths, output_path, list_file_path):
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in wav_paths:
            normalized = str(path).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{normalized}'\n")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file_path), "-c", "copy", str(output_path)])


def download_single(query, temp_dir):
    outtmpl = str(temp_dir / "%(title)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if info is None:
                raise RuntimeError("Could not find or download that.")
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise RuntimeError("No results found for that search.")
                info = entries[0]
            return Path(ydl.prepare_filename(info))
    except DownloadError as e:
        raise RuntimeError(f"Download failed: {e}") from e


def search_youtube_candidates(query, count=5):
    opts = {"format": "bestaudio/best", "quiet": True, "no_warnings": True}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    except DownloadError as e:
        raise RuntimeError(f"Search failed: {e}") from e
    return [e for e in (info.get("entries") or []) if e]


def pick_best_candidate(candidates, target_duration_sec=None):
    if not candidates:
        return None
    if not target_duration_sec:
        return candidates[0]
    return min(candidates, key=lambda e: abs((e.get("duration") or 0) - target_duration_sec))


def download_by_url(url, temp_dir):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info))
    except DownloadError as e:
        raise RuntimeError(f"Download failed: {e}") from e


def search_and_download(query, temp_dir, target_duration_sec=None, candidates=5):
    found = search_youtube_candidates(query, candidates)
    if not found:
        raise RuntimeError(f"No results found for: {query}")
    best = pick_best_candidate(found, target_duration_sec)
    return download_by_url(best["webpage_url"], temp_dir)


def download_youtube_playlist(url, temp_dir):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(playlist_index)03d - %(title)s.%(ext)s"),
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        raise RuntimeError(f"Playlist download failed: {e}") from e
    if info is None:
        raise RuntimeError("Could not read that playlist.")
    title = info.get("title") or "playlist"
    files = sorted(
        p for p in temp_dir.iterdir()
        if p.is_file() and p.suffix not in (".part", ".ytdl")
    )
    return title, files


def build_spotify_authorize_url(client_id, redirect_uri, state):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPES,
        "state": state,
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


def exchange_spotify_code(code, client_id, client_secret, redirect_uri):
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError("Spotify login failed. Please try connecting again.")
    return resp.json()


def refresh_spotify_token(refresh_token, client_id, client_secret):
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        auth=(client_id, client_secret),
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError("Could not refresh Spotify session.")
    return resp.json()


def fetch_spotify_playlist(playlist_id, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    meta_resp = requests.get(
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
        headers=headers,
        params={"fields": "name"},
        timeout=10,
    )
    if meta_resp.status_code == 401:
        raise RuntimeError("Spotify session expired. Please reconnect.")
    if meta_resp.status_code != 200:
        raise RuntimeError("Could not read that Spotify playlist.")
    playlist_name = meta_resp.json().get("name") or "Spotify Playlist"

    tracks = []
    endpoint = f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items"
    params = {"limit": 50}
    while endpoint:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=10)
        if resp.status_code == 401:
            raise RuntimeError("Spotify session expired. Please reconnect.")
        if resp.status_code == 403:
            raise RuntimeError("This playlist isn't accessible. You can only read playlists you own or collaborate on.")
        if resp.status_code != 200:
            raise RuntimeError("Failed while reading playlist tracks from Spotify.")
        data = resp.json()
        entries = data.get("items")
        if entries is None:
            raise RuntimeError("This playlist isn't accessible. You can only read playlists you own or collaborate on.")
        for entry in entries:
            item = entry.get("item") or entry.get("track")
            if not item or not item.get("name"):
                continue
            artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            tracks.append({
                "name": item["name"],
                "artist": artists,
                "duration_sec": (item.get("duration_ms") or 0) / 1000,
            })
        endpoint = data.get("next")
        params = None
    if not tracks:
        raise RuntimeError("No accessible tracks found in that playlist.")
    return playlist_name, tracks


def process_song(query, output_format, downloads_dir, temp_dir, report=print, output_name=None):
    report(f"Searching: {query}")
    search_query = query if is_url(query) else f"ytsearch1:{query}"
    raw_path = download_single(search_query, temp_dir)
    name = output_name or raw_path.stem
    final_path = downloads_dir / (sanitize_filename(name) + f".{output_format}")
    report("Encoding final audio...")
    encode_final(raw_path, final_path, output_format)
    return final_path


def process_youtube_playlist(url, output_format, downloads_dir, temp_dir, report=print, output_name=None, should_cancel=None):
    report("Reading playlist...")
    title, raw_files = download_youtube_playlist(url, temp_dir)
    if not raw_files:
        raise RuntimeError("No tracks could be downloaded from this playlist.")
    report(f"Downloaded {len(raw_files)} tracks. Standardizing audio...")
    wav_dir = temp_dir / "wav"
    wav_dir.mkdir(exist_ok=True)
    wav_files = []
    for i, raw in enumerate(raw_files, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("Cancelled.")
        wav_path = wav_dir / f"{i:03d}.wav"
        convert_to_wav(raw, wav_path)
        wav_files.append(wav_path)
        report(f"Processed {i}/{len(raw_files)}")
    merged_wav = temp_dir / "merged.wav"
    list_file = temp_dir / "concat_list.txt"
    report("Merging tracks in order...")
    concat_wavs(wav_files, merged_wav, list_file)
    name = output_name or title
    final_path = downloads_dir / (sanitize_filename(name) + f".{output_format}")
    report("Encoding final audio...")
    encode_final(merged_wav, final_path, output_format)
    return final_path


def normalize_tracklist(raw):
    if not isinstance(raw, list):
        raise RuntimeError("Tracklist JSON must be a list of songs.")
    tracks = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("song") or entry.get("name") or entry.get("title")
        artist = entry.get("artist") or entry.get("artists")
        if isinstance(artist, list):
            artist = ", ".join(str(a) for a in artist)
        if not name:
            continue
        tracks.append({"name": str(name), "artist": str(artist or "").strip(), "duration_sec": None})
    if not tracks:
        raise RuntimeError("No valid song entries found in that JSON.")
    return tracks


def process_tracklist(tracks, playlist_name, output_format, downloads_dir, temp_dir, report=print, should_cancel=None):
    total = len(tracks)
    report(f"Processing {total} tracks from '{playlist_name}'.")

    wav_dir = temp_dir / "wav"
    wav_dir.mkdir(exist_ok=True)
    wav_files = []
    resolved_tracklist = []
    for i, track in enumerate(tracks, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("Cancelled.")
        query = f"{track['name']} {track['artist']}".strip()
        report(f"[{i}/{total}] Searching: {query}")
        try:
            raw_path = search_and_download(query, temp_dir, target_duration_sec=track.get("duration_sec"))
        except Exception as e:
            report(f"[{i}/{total}] Skipped ({e})")
            continue
        wav_path = wav_dir / f"{i:03d}.wav"
        convert_to_wav(raw_path, wav_path)
        wav_files.append(wav_path)
        resolved_tracklist.append({"name": track["name"], "artist": track["artist"]})
        report(f"[{i}/{total}] Done: {track['name']}")

    if not wav_files:
        raise RuntimeError("None of the tracks could be found on YouTube.")

    merged_wav = temp_dir / "merged.wav"
    list_file = temp_dir / "concat_list.txt"
    report("Merging tracks in order...")
    concat_wavs(wav_files, merged_wav, list_file)

    final_path = downloads_dir / (sanitize_filename(playlist_name) + f".{output_format}")
    report("Encoding final audio...")
    encode_final(merged_wav, final_path, output_format)

    tracklist_path = downloads_dir / (sanitize_filename(playlist_name) + "_tracklist.json")
    with open(tracklist_path, "w", encoding="utf-8") as f:
        json.dump(resolved_tracklist, f, ensure_ascii=False, indent=2)

    report(f"Tracklist saved: {tracklist_path}")
    return final_path, resolved_tracklist


def process_spotify_playlist(url, access_token, output_format, downloads_dir, temp_dir, report=print, should_cancel=None):
    report("Reading Spotify playlist...")
    playlist_id = extract_spotify_playlist_id(url)
    playlist_name, spotify_tracks = fetch_spotify_playlist(playlist_id, access_token)
    report(f"Found {len(spotify_tracks)} tracks in '{playlist_name}'.")
    return process_tracklist(spotify_tracks, playlist_name, output_format, downloads_dir, temp_dir, report, should_cancel)
