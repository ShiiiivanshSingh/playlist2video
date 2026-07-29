import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import core
from converter import export_video


def main():
    parser = argparse.ArgumentParser(description="Download a song or playlist as one high quality audio file.")
    parser.add_argument("query", nargs="?", help="Song name, YouTube playlist URL, or direct video URL")
    parser.add_argument("--format", choices=core.SUPPORTED_FORMATS, default=core.DEFAULT_FORMAT)
    parser.add_argument("--tracklist", help="Path to a JSON file: [{\"song\": ..., \"artist\": ...}, ...]")
    parser.add_argument("--name", help="Output file name (defaults to the song/playlist/file name)")
    parser.add_argument("--output-dir", help="Folder to save into (defaults to your Downloads folder)")
    parser.add_argument("--make-video", action="store_true",
                        help="After downloading, combine with a background image to produce a 1080p MP4")
    parser.add_argument("--image", help="Path to background image (required when --make-video is set)")
    args = parser.parse_args()

    if not core.check_ffmpeg_available():
        print("ffmpeg was not found on this system.")
        print("Install it first:")
        print("  Windows: winget install ffmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        sys.exit(1)

    if args.make_video:
        if not args.image:
            print("--image PATH is required when using --make-video.")
            sys.exit(1)
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"Image file not found: {image_path}")
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
            final_audio, _ = core.process_tracklist(tracks, playlist_name, args.format, downloads_dir, temp_dir)
            if args.make_video:
                print("\nCreating video...")
                video_path = final_audio.with_suffix(".mp4")
                export_video(image_path=str(image_path), audio_path=str(final_audio), output_path=str(video_path),
                             progress_callback=lambda f: print(f"  Video encoding: {int(f*100)}%", end="\r"))
                final_audio.unlink(missing_ok=True)
                print(f"\nSaved: {video_path}")
            else:
                print(f"\nSaved: {final_audio}")
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
            final_audio = core.process_youtube_playlist(query, args.format, downloads_dir, temp_dir, output_name=args.name)
        else:
            final_audio = core.process_song(query, args.format, downloads_dir, temp_dir, output_name=args.name)

        if args.make_video:
            print("\nCreating video...")
            video_path = final_audio.with_suffix(".mp4")
            export_video(image_path=str(image_path), audio_path=str(final_audio), output_path=str(video_path),
                         progress_callback=lambda f: print(f"  Video encoding: {int(f*100)}%", end="\r"))
            final_audio.unlink(missing_ok=True)
            print(f"\nSaved: {video_path}")
        else:
            print(f"\nSaved: {final_audio}")
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
