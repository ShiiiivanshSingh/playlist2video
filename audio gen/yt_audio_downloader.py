import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import core


def main():
    parser = argparse.ArgumentParser(description="Download a song or playlist as one high quality audio file.")
    parser.add_argument("query", nargs="?", help="Song name, YouTube playlist URL, or direct video URL")
    parser.add_argument("--format", choices=core.SUPPORTED_FORMATS, default=core.DEFAULT_FORMAT)
    parser.add_argument("--tracklist", help="Path to a JSON file: [{\"song\": ..., \"artist\": ...}, ...]")
    parser.add_argument("--name", help="Output file name (defaults to the song/playlist/file name)")
    parser.add_argument("--output-dir", help="Folder to save into (defaults to your Downloads folder)")
    args = parser.parse_args()

    if not core.check_ffmpeg_available():
        print("ffmpeg was not found on this system.")
        print("Install it first:")
        print("  Windows: winget install ffmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        sys.exit(1)

    try:
        downloads_dir = core.resolve_output_dir(args.output_dir)
    except Exception as e:
        print(f"Could not use that output folder: {e}")
        sys.exit(1)
    temp_dir = Path(tempfile.mkdtemp(prefix="audio_dl_"))

    try:
        if args.tracklist:
            tracklist_path = Path(args.tracklist)
            if not tracklist_path.exists():
                print(f"File not found: {tracklist_path}")
                sys.exit(1)
            raw = json.loads(tracklist_path.read_text(encoding="utf-8"))
            tracks = core.normalize_tracklist(raw)
            playlist_name = args.name or tracklist_path.stem
            final_path, _ = core.process_tracklist(tracks, playlist_name, args.format, downloads_dir, temp_dir)
            print(f"\nSaved: {final_path}")
            return

        query = args.query or input("Enter a song name or YouTube playlist URL: ").strip()
        if not query:
            print("No input provided.")
            sys.exit(1)

        if core.is_spotify_url(query):
            print("Spotify links aren't supported directly (Spotify blocks free-tier API access).")
            print("Export the playlist as a JSON file of songs and artists, then run:")
            print("  python yt_audio_downloader.py --tracklist your_file.json")
            sys.exit(1)

        if core.is_youtube_playlist_url(query):
            final_path = core.process_youtube_playlist(query, args.format, downloads_dir, temp_dir, output_name=args.name)
        else:
            final_path = core.process_song(query, args.format, downloads_dir, temp_dir, output_name=args.name)
        print(f"\nSaved: {final_path}")
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
