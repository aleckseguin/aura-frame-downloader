# /// script
# requires-python = ">=3.10"
# ///
"""
Move the video half of Live Photos out of an aura-frame-downloader folder,
leaving the still photo and any real videos in place.

How it tells them apart (from the JSON saved with --save-assets):
  - Live Photo motion clip: Aura marks the asset with Apple's Live Photo flag
    (ios_media_subtypes includes 8) or records no clip length (duration 0).
  - Real video: everything else that has a video file.

Files are MOVED, not deleted, into a "_live_photo_videos" folder inside the
photo folder, so you can check them before deleting the folder yourself.

Usage
-----
    uv run remove_live_photo_videos.py ASSETS_JSON PHOTO_FOLDER          # dry run
    uv run remove_live_photo_videos.py ASSETS_JSON PHOTO_FOLDER --apply  # move them
"""

import argparse
import json
import re
import shutil
from pathlib import Path

ID_RE = re.compile(r"_([0-9a-fA-F-]{36})\.([A-Za-z0-9]+)$")
VIDEO_EXT = {"mp4", "mov", "m4v"}
LIVE_PHOTO_FLAG = 8  # Apple's PHAssetMediaSubtype.photoLive


def is_live_photo_clip(asset: dict) -> bool:
    return bool((asset.get("ios_media_subtypes") or 0) & LIVE_PHOTO_FLAG) or not asset.get("duration")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("assets_json", type=Path)
    p.add_argument("photo_folder", type=Path)
    p.add_argument("--apply", action="store_true", help="Actually move the files (default is a dry run)")
    args = p.parse_args()

    assets = {a["id"].lower(): a for a in json.loads(args.assets_json.read_text())["assets"]}
    dest_root = args.photo_folder / "_live_photo_videos"

    live, real, unknown = [], [], []
    for path in sorted(args.photo_folder.rglob("*")):
        if not path.is_file() or dest_root in path.parents:
            continue
        m = ID_RE.search(path.name)
        if not m or m.group(2).lower() not in VIDEO_EXT:
            continue
        asset = assets.get(m.group(1).lower())
        if asset is None:
            unknown.append(path)
        elif is_live_photo_clip(asset):
            live.append(path)
        else:
            real.append(path)

    print(f"\nFolder: {args.photo_folder}")
    print(f"  Live Photo video clips (will be moved): {len(live)}")
    print(f"  Real videos (kept):                     {len(real)}")
    if unknown:
        print(f"  Videos not in this JSON (left alone):   {len(unknown)}")
    for path in real[:5]:
        dur = assets[ID_RE.search(path.name).group(1).lower()].get("duration")
        print(f"    kept: {path.name}  ({dur:.0f}s)")

    if not args.apply:
        print("\nDry run only. Nothing was moved. Add --apply to move the Live Photo clips.")
        return

    for path in live:
        target = dest_root / path.relative_to(args.photo_folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    print(f"\nMoved {len(live)} files into {dest_root}")
    print("Check a few, then delete that folder when you're happy.")


if __name__ == "__main__":
    main()
