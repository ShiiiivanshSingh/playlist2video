import json
import sys
from pathlib import Path


def parse_line(line):
    line = line.strip()
    if not line or " - " not in line:
        return None
    artists_part, title = line.split(" - ", 1)
    artists = [a.strip() for a in artists_part.split(",") if a.strip()]
    title = title.strip()
    if not title or not artists:
        return None
    return {"song": title, "artist": ", ".join(artists)}


def convert(input_path, output_path):
    lines = Path(input_path).read_text(encoding="utf-8").splitlines()
    tracks = []
    skipped = []
    for line in lines:
        parsed = parse_line(line)
        if parsed:
            tracks.append(parsed)
        elif line.strip():
            skipped.append(line)
    Path(output_path).write_text(json.dumps(tracks, ensure_ascii=False, indent=2), encoding="utf-8")
    return tracks, skipped


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python spotify_paste_to_json.py input.txt output.json")
        sys.exit(1)
    tracks, skipped = convert(sys.argv[1], sys.argv[2])
    print(f"Converted {len(tracks)} tracks -> {sys.argv[2]}")
    if skipped:
        print(f"Skipped {len(skipped)} unparseable lines:")
        for s in skipped:
            print(f"  {s}")
