# /// script
# requires-python = ">=3.10"
# dependencies = ["timezonefinder>=6.5"]
# ///
"""
Write the original date/time (and GPS location, when Aura has it) back into
photos and videos downloaded with aura-frame-downloader.

How it works
------------
Each downloaded file is named  <taken_at>_<asset id>.<ext>, for example
    2025-07-14T15-22-08.405Z_01a10e8c-5867-740d-94af-e451444fd4ca.heic
The script pulls the asset id out of the filename, looks it up in the JSON
saved with --save-assets, and uses exiftool to write:

  Photos (HEIC/JPEG/PNG): DateTimeOriginal, CreateDate, ModifyDate,
                          OffsetTime* (time zone) and GPS latitude/longitude
  Videos (MP4/MOV):       QuickTime create dates, Apple's CreationDate and
                          GPS coordinates

Aura stores times in UTC. Photo metadata wants local time, so the script works
out the time zone from the photo's GPS location (so Alberta photos get Mountain
time, etc.). Photos without a location use --default-tz (Toronto by default).

Usage
-----
    uv run add_aura_metadata.py ASSETS_JSON PHOTO_FOLDER            # dry run
    uv run add_aura_metadata.py ASSETS_JSON PHOTO_FOLDER --apply    # write it

Requires exiftool on your PATH (macOS: brew install exiftool).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from timezonefinder import TimezoneFinder

ID_RE = re.compile(r"_([0-9a-fA-F-]{36})\.([A-Za-z0-9]+)$")
PHOTO_EXT = {"heic", "heif", "jpg", "jpeg", "png"}
VIDEO_EXT = {"mp4", "mov", "m4v"}

# First bytes of each real file type, to catch a ".heic" that is really a JPEG.
MAGIC = {
    "jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "isobmff": lambda b: b[4:8] == b"ftyp",  # HEIC, MP4 and MOV all use this
}


def real_type(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(16)
    for name, test in MAGIC.items():
        if test(head):
            return name
    return "unknown"


def expected_type(ext: str) -> str:
    if ext in ("jpg", "jpeg"):
        return "jpeg"
    if ext == "png":
        return "png"
    return "isobmff"


def valid_location(loc) -> tuple[float, float] | None:
    """Aura stores [longitude, latitude]. Returns (lat, lon) or None."""
    if not loc or len(loc) != 2:
        return None
    lon, lat = float(loc[0]), float(loc[1])
    if lat == 0 and lon == 0:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def build_args(path: Path, asset: dict, tf: TimezoneFinder, default_tz: ZoneInfo):
    ext = path.suffix.lower().lstrip(".")
    utc = datetime.fromisoformat(asset["taken_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    latlon = valid_location(asset.get("location"))

    tz = default_tz
    tz_source = "default"
    if latlon:
        name = tf.timezone_at(lat=latlon[0], lng=latlon[1])
        if name:
            tz, tz_source = ZoneInfo(name), "gps"

    local = utc.astimezone(tz)
    stamp = local.strftime("%Y:%m:%d %H:%M:%S")
    offset = local.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}"  # -0400 -> -04:00

    args = []
    if ext in PHOTO_EXT:
        for tag in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
            args.append(f"-{tag}={stamp}")
        for tag in ("OffsetTimeOriginal", "OffsetTimeDigitized", "OffsetTime"):
            args.append(f"-{tag}={offset}")
        if latlon:
            lat, lon = latlon
            args += [
                f"-GPSLatitude={abs(lat)}",
                f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
                f"-GPSLongitude={abs(lon)}",
                f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
            ]
    elif ext in VIDEO_EXT:
        # With -api QuickTimeUTC, exiftool converts these local times (with
        # offset) to UTC, which is what the QuickTime spec requires.
        for tag in ("QuickTime:CreateDate", "QuickTime:ModifyDate",
                    "QuickTime:TrackCreateDate", "QuickTime:TrackModifyDate",
                    "QuickTime:MediaCreateDate", "QuickTime:MediaModifyDate"):
            args.append(f"-{tag}={stamp}{offset}")
        # Apple Photos reads this one first, and it keeps the time zone.
        args.append(f"-Keys:CreationDate={stamp}{offset}")
        if latlon:
            args.append(f"-Keys:GPSCoordinates={latlon[0]}, {latlon[1]}")
    else:
        return None, None

    # Also set the file's own modified date so Finder sorts sensibly.
    args.append(f"-FileModifyDate={stamp}{offset}")
    return args, {"local": f"{stamp}{offset}", "tz": str(tz), "tz_source": tz_source, "gps": latlon}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("assets_json", type=Path, help="JSON saved with --save-assets")
    p.add_argument("photo_folder", type=Path, help="Folder the photos were downloaded to (searched recursively)")
    p.add_argument("--apply", action="store_true", help="Actually write metadata (default is a dry run)")
    p.add_argument("--default-tz", default="America/Toronto",
                   help="Time zone for photos with no location (default: America/Toronto)")
    p.add_argument("--keep-backups", action="store_true",
                   help="Keep exiftool's *_original backup copies (doubles disk use)")
    args = p.parse_args()

    if args.apply and not shutil.which("exiftool"):
        sys.exit("exiftool not found. Install it with:  brew install exiftool")

    data = json.loads(args.assets_json.read_text())
    assets = {a["id"].lower(): a for a in data["assets"]}
    tf = TimezoneFinder()
    default_tz = ZoneInfo(args.default_tz)

    stats = Counter()
    mismatched, unmatched, samples, blocks = [], [], [], []

    for path in sorted(args.photo_folder.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if "_live_photo_videos" in path.relative_to(args.photo_folder).parts:
            continue
        m = ID_RE.search(path.name)
        if not m:
            continue
        stats["files found"] += 1
        asset = assets.get(m.group(1).lower())
        if not asset:
            unmatched.append(path)
            continue

        ext = m.group(2).lower()
        actual = real_type(path)
        if actual != expected_type(ext):
            mismatched.append((path, actual))
            continue

        tag_args, info = build_args(path, asset, tf, default_tz)
        if tag_args is None:
            stats["skipped (unsupported type)"] += 1
            continue

        stats["videos" if ext in VIDEO_EXT else "photos"] += 1
        stats["with location"] += bool(info["gps"])
        stats["time zone from GPS"] += info["tz_source"] == "gps"
        if asset["taken_at"].startswith("1980-01-01"):
            stats["dated 1980-01-01 (likely wrong in Aura)"] += 1
        if len(samples) < 5:
            samples.append((path.name, info))
        blocks.append((path, tag_args))

    print(f"\nFolder: {args.photo_folder}")
    for k, v in stats.items():
        print(f"  {k:42} {v}")
    if unmatched:
        print(f"  {'not in this JSON (other frame?)':42} {len(unmatched)}")
    if mismatched:
        print(f"  {'extension does not match contents':42} {len(mismatched)}  (skipped; see below)")

    print("\nExamples:")
    for name, info in samples:
        loc = f"{info['gps'][0]:.4f}, {info['gps'][1]:.4f}" if info["gps"] else "no location"
        print(f"  {name}\n      -> {info['local']}  [{info['tz']}, {info['tz_source']}]  {loc}")

    if mismatched:
        print("\nFiles whose extension doesn't match their contents (first 5):")
        for path, actual in mismatched[:5]:
            print(f"  {path.name}  (actually {actual})")

    if not args.apply:
        print("\nDry run only. Nothing was changed. Add --apply to write the metadata.")
        return
    if not blocks:
        print("\nNothing to write.")
        return

    # One exiftool process for everything: much faster than one per file.
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        for path, tag_args in blocks:
            f.write("\n".join(tag_args) + f"\n{path}\n-execute\n")
        argfile = f.name

    # -common_args applies these options to every -execute block in the argfile.
    cmd = ["exiftool", "-@", argfile, "-common_args", "-charset", "filename=utf8",
           "-api", "QuickTimeUTC=1", "-m"]
    if not args.keep_backups:
        cmd.append("-overwrite_original")

    print(f"\nWriting metadata to {len(blocks)} files with exiftool...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = (result.stdout + result.stderr).splitlines()
    updated = sum(1 for line in out if "image files updated" in line and line.strip().startswith("1 "))
    errors = [line for line in out if line.startswith(("Error", "Warning"))]
    print(f"Updated: {updated} of {len(blocks)}")
    if errors:
        print(f"{len(errors)} errors/warnings (first 10):")
        for line in errors[:10]:
            print("  " + line)
    Path(argfile).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
