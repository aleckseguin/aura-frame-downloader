# /// script
# requires-python = ">=3.10"
# ///
"""
Rename downloaded photos whose extension doesn't match what's inside them.

Aura serves JPEG copies of most photos but keeps the original filename, so a
"photo.heic" is usually a JPEG. exiftool refuses to write to those, so run this
before add_aura_metadata.py. Only the extension changes:
    2024-01-01T16-52-30.535Z_<asset id>.heic  ->  ...<asset id>.jpg

Files inside _live_photo_videos are left alone, as is any file whose new name
already exists. exiftool *_original backups are renamed with their photo.
Every rename is logged to _rename_log.tsv (old<TAB>new) in the photo folder,
so it can be undone.

Usage
-----
    uv run fix_photo_extensions.py PHOTO_FOLDER          # dry run
    uv run fix_photo_extensions.py PHOTO_FOLDER --apply  # rename them
"""

import argparse
from pathlib import Path

PHOTO_EXT = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
SKIP_DIRS = {"_live_photo_videos"}


def correct_suffix(path: Path) -> str | None:
    """The extension the file's contents call for, or None if it already fits."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:3] == b"\xff\xd8\xff":
        return None if path.suffix.lower() in (".jpg", ".jpeg") else ".jpg"
    if head == b"\x89PNG\r\n\x1a\n":
        return None if path.suffix.lower() == ".png" else ".png"
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("photo_folder", type=Path)
    p.add_argument("--apply", action="store_true", help="Actually rename the files (default is a dry run)")
    args = p.parse_args()

    todo, clashes = [], []
    for path in sorted(args.photo_folder.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in PHOTO_EXT:
            continue
        if SKIP_DIRS & set(path.relative_to(args.photo_folder).parts):
            continue
        suffix = correct_suffix(path)
        if suffix is None:
            continue
        target = path.with_suffix(suffix)
        (clashes if target.exists() else todo).append((path, target))

    print(f"\nFolder: {args.photo_folder}")
    print(f"  Files to rename:                  {len(todo)}")
    if clashes:
        print(f"  Skipped (new name already taken): {len(clashes)}")
    for old, new in todo[:5]:
        print(f"    {old.name} -> {new.suffix}")

    if not args.apply:
        print("\nDry run only. Nothing was renamed. Add --apply to rename them.")
        return

    log_path = args.photo_folder / "_rename_log.tsv"
    with open(log_path, "a", encoding="utf-8") as log:
        for old, new in todo:
            old.rename(new)
            log.write(f"{old}\t{new}\n")
            # Keep any exiftool backup paired with its photo.
            backup = old.with_name(old.name + "_original")
            new_backup = new.with_name(new.name + "_original")
            if backup.exists() and not new_backup.exists():
                backup.rename(new_backup)
                log.write(f"{backup}\t{new_backup}\n")
    print(f"\nRenamed {len(todo)} files. Undo log: {log_path}")


if __name__ == "__main__":
    main()
