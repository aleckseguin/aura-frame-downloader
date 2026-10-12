# /// script
# requires-python = ">=3.10"
# ///
"""
Sort an aura-frame-downloader folder into one folder per uploader (the person
who added each photo to the frame), using the JSON saved with --save-assets.

Photos whose date is probably wrong go into a separate _date_uncertain folder
so you can check them by eye:
  - dated 1980-01-01 (Aura's placeholder for an unknown date), or
  - no GPS location and dated within --uncertain-minutes of the upload time.
    These usually reached Aura with no date of their own (forwarded or saved
    images), so Aura used roughly the time they were added to the frame.

Result:
    PHOTO_FOLDER/<Uploader>/...
    PHOTO_FOLDER/_date_uncertain/<Uploader>/...
    PHOTO_FOLDER/_live_photo_videos/...            (untouched)

Files are moved, never deleted or overwritten. exiftool *_original backups move
with their photo. Every move is logged to _move_log.tsv (old<TAB>new) in the
photo folder, and folders left empty (such as year folders) are removed.

Usage
-----
    uv run organize_by_uploader.py ASSETS_JSON PHOTO_FOLDER          # dry run
    uv run organize_by_uploader.py ASSETS_JSON PHOTO_FOLDER --apply  # move them
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ID_RE = re.compile(r"_([0-9a-fA-F-]{36})\.([A-Za-z0-9]+)$")
UNCERTAIN_DIR = "_date_uncertain"
SKIP_DIRS = {"_live_photo_videos"}


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def date_uncertain(asset: dict, window_seconds: float) -> bool:
    if asset["taken_at"].startswith("1980-01-01"):
        return True
    if asset.get("location") or not asset.get("uploaded_at"):
        return False
    gap = parse_time(asset["uploaded_at"]) - parse_time(asset["taken_at"])
    return abs(gap.total_seconds()) < window_seconds


def folder_name(asset: dict) -> str:
    name = (asset.get("user") or {}).get("name") or "Unknown"
    return re.sub(r"[/:\\]", "-", name).strip() or "Unknown"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("assets_json", type=Path, help="JSON saved with --save-assets")
    p.add_argument("photo_folder", type=Path)
    p.add_argument("--apply", action="store_true", help="Actually move the files (default is a dry run)")
    p.add_argument("--uncertain-minutes", type=float, default=60,
                   help="No-GPS photos dated this close to their upload go to _date_uncertain (default: 60, 0 turns it off)")
    args = p.parse_args()

    assets = {a["id"].lower(): a for a in json.loads(args.assets_json.read_text())["assets"]}
    window = args.uncertain_minutes * 60

    moves, unmatched, clashes, stats = [], [], [], Counter()
    for path in sorted(args.photo_folder.rglob("*")):
        rel = path.relative_to(args.photo_folder)
        if not path.is_file() or path.name.startswith(".") or SKIP_DIRS & set(rel.parts):
            continue
        m = ID_RE.search(path.name)
        if not m:
            continue
        asset = assets.get(m.group(1).lower())
        if asset is None:
            unmatched.append(path)
            continue

        group = folder_name(asset)
        if date_uncertain(asset, window):
            group = f"{UNCERTAIN_DIR}/{group}"
        dest = args.photo_folder / group / path.name
        if dest == path:
            continue
        if dest.exists():
            clashes.append(path)
            continue
        moves.append((path, dest))
        backup = path.with_name(path.name + "_original")
        if backup.exists():
            moves.append((backup, dest.with_name(dest.name + "_original")))
        stats[group] += 1

    print(f"\nFolder: {args.photo_folder}")
    for group, n in sorted(stats.items()):
        print(f"  {group:42} {n}")
    if unmatched:
        print(f"  {'not in this JSON (left in place)':42} {len(unmatched)}")
    if clashes:
        print(f"  {'already exists at destination (left)':42} {len(clashes)}")

    if not args.apply:
        print("\nDry run only. Nothing was moved. Add --apply to move the files.")
        return

    log_path = args.photo_folder / "_move_log.tsv"
    with open(log_path, "a", encoding="utf-8") as log:
        for old, new in moves:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            log.write(f"{old}\t{new}\n")

    # Remove folders the moves emptied, deepest first. Only Finder's .DS_Store
    # is cleared; any folder with anything else in it is kept.
    removed = 0
    emptied = {old.parent for old, _ in moves} - {args.photo_folder}
    for d in sorted(emptied, key=lambda d: len(d.parts), reverse=True):
        if (d / ".DS_Store").exists() and len(list(d.iterdir())) == 1:
            (d / ".DS_Store").unlink()
        try:
            d.rmdir()
            removed += 1
        except OSError:
            pass
    print(f"\nMoved {sum(stats.values())} files into uploader folders, removed {removed} empty folders.")
    print(f"Undo log: {log_path}")


if __name__ == "__main__":
    main()
