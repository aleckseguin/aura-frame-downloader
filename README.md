# Aura Frame Downloader

Bulk download photos from your Aura digital picture frame (auraframes.com). Aura provides no easy way to bulk download photos, so this tool lets you download all your photos at once. Since Aura stores photos on their servers, no physical access to the frame is needed.

---

## Download & Install (Easiest)

### macOS (Apple Silicon)

1. **Download** the latest release: [Aura-Downloader-macOS-arm64.zip](https://github.com/meub/aura-frame-downloader/releases/latest/download/Aura-Downloader-macOS-arm64.zip)

2. **Unzip** and drag `Aura Downloader.app` to your Applications folder

3. **First launch** - Right-click the app and select "Open" (required once since the app isn't signed by Apple)
   - If you see "app is damaged", run this in Terminal:
     ```bash
     xattr -cr "/Applications/Aura Downloader.app"
     ```

4. **Use the app:**
   - Enter your Aura email and password
   - Click "Add Frame" and enter your frame details (see [Getting your Frame ID](#getting-your-frame-id) below)
   - Select a download folder
   - Click "Start Download"

Your credentials and frame settings are saved automatically for next time.

### Windows

1. **Download** the latest release: [Aura-Downloader-Windows.zip](https://github.com/meub/aura-frame-downloader/releases/latest)

2. **Unzip** and run `Aura Downloader.exe`
   - Windows may show a SmartScreen warning since the app isn't signed
   - Click "More info" then "Run anyway"

3. **Use the app:**
   - Enter your Aura email and password
   - Click "Add Frame" and enter your frame details (see [Getting your Frame ID](#getting-your-frame-id) below)
   - Select a download folder
   - Click "Start Download"

Your credentials and frame settings are saved automatically for next time.

---

## Getting your Frame ID

1. Go to https://app.auraframes.com and log in
2. Click on the Frame name
3. Click on "View Photos" underneath the frame
4. Grab the ID from the URL: `https://app.auraframes.com/frame/<FRAME ID HERE>`

---

## Command Line Usage

If you prefer the command line or are on Windows/Linux:

### Setup

1. Install Python 3 and the requests module:
   ```bash
   pip install requests
   ```

2. Create a configuration file at:
   - **Windows:** `%USERPROFILE%/etc/aura/credentials.ini`
   - **Mac/Linux:** `$HOME/etc/aura/credentials.ini`

   Example config:
   ```ini
   [login]
   email = myemail@gmail.com
   password = mypassword

   [myframe]
   file_path = ./images
   frame_id = abf53be3-b73d-4de3-98cd-cfd289bd82df

   [anotherframe]
   file_path = ./images-another-frame
   frame_id = b69ddd8d-bcad-483f-adf4-e15ff9a48c47
   ```

### Commands

```bash
# Download photos from a frame
python download-aura-photos.py myframe

# Show photo count only
python download-aura-photos.py --count myframe

# Organize by year folders
python download-aura-photos.py --years myframe

# Only download video clips (skip stills)
python download-aura-photos.py --videos-only myframe

# Save raw API JSON to a file (for debugging)
python download-aura-photos.py --save-assets /tmp/aura-assets.json myframe

# Only download photos added since the last run, even if earlier ones were moved or deleted
python download-aura-photos.py --history ~/Pictures/myframe-history.txt myframe

# Use alternate config file
python download-aura-photos.py --config /path/to/config.ini myframe
```

### Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Use alternate configuration file |
| `--count` | Show photo count and exit |
| `--years` | Organize photos into year subfolders |
| `--videos-only` | Only download video clips, skip still photos |
| `--save-assets FILE` | Write the raw asset JSON returned by the Aura API to FILE |
| `--history FILE` | Skip photos listed in FILE and add each new download to it |
| `--debug` | Enable debug logging |

---

## Moving Photos to Apple Photos / iCloud

Aura's downloads have no date or location stored inside the files, and most `.heic` files are really JPEGs, so Photos would file everything under the day you import it. The helper scripts in this folder fix that before you import. Do this once per frame; each frame gets its own folder, JSON file and history file.

### What you need

- The command line setup above, with a section for the frame in `credentials.ini`. **The download folder is that section's `file_path`**; the scripts below must be pointed at the same folder.
- [uv](https://docs.astral.sh/uv/) to run the helper scripts, and exiftool for the last step: `brew install exiftool`. If a script says exiftool isn't found even though it's installed, Homebrew isn't on your PATH: run `eval "$(/opt/homebrew/bin/brew shellenv)"` and try again.
- Run every command from this repository's folder.

### Steps

Set these once in your terminal so the commands below can be pasted as is. Change `myframe` to the frame's section name in `credentials.ini`:

```bash
FRAME=myframe
DIR=~/Pictures/aura-myframe                  # must match file_path for [myframe]
JSON=~/Pictures/aura-myframe-assets.json     # Aura's photo details, rewritten on every download
HIST=~/Pictures/aura-myframe-history.txt     # list of photos already downloaded; never delete it
```

Every helper script only reports what it would do unless you add `--apply`. Run each one without `--apply` first, check the counts, then run it again with `--apply`. None of them delete anything.

```bash
# 1. Download. Only photos not already in $HIST are fetched.
python download-aura-photos.py --save-assets "$JSON" --history "$HIST" "$FRAME"

# 2. Move the video half of Live Photos into $DIR/_live_photo_videos/
uv run remove_live_photo_videos.py "$JSON" "$DIR" --apply

# 3. Rename .heic/.png files that are really JPEGs to .jpg (exiftool can't write to them otherwise)
uv run fix_photo_extensions.py "$DIR" --apply

# 4. Sort into one folder per uploader; doubtful dates go in $DIR/_date_uncertain/
uv run organize_by_uploader.py "$JSON" "$DIR" --apply

# 5. Write each photo's date, time zone and GPS location into the file
uv run add_aura_metadata.py "$JSON" "$DIR" --apply --keep-backups
```

### Checking and importing

1. **Spot-check a few files** in Finder (Get Info) or with `exiftool -DateTimeOriginal -GPSPosition FILE`.
2. **Delete the backups** once you're happy: `exiftool -r -delete_original "$DIR"`. Step 5 left an untouched `*_original` copy beside every file in case something went wrong; these must not be imported. To undo step 5 instead, use `exiftool -r -restore_original "$DIR"`.
3. **Import** in Photos with File → Import, choosing the uploader folders and `_date_uncertain`. To keep track of who uploaded what, import one uploader folder at a time into a new album named after them. Leave out `_live_photo_videos` (Photos can't rejoin those clips to their photos) and the `.tsv` log files.
4. **Fix uncertain dates** in Photos (Image → Adjust Date and Time). Photos in `_date_uncertain` had no location and are dated within an hour of when they were uploaded to Aura, which usually means the file reached Aura with no date and Aura used the upload time. Change the one-hour window with `--uncertain-minutes`.
5. **Duplicates:** a photo added to more than one frame is downloaded once per frame. Photos warns about duplicates on import, and lists any it finds later in the Duplicates album.

### Next time

After importing, delete `$DIR` but **keep `$HIST`**. The next download recreates the folder and fetches only photos added to the frame since the last run, so run the same steps again. The JSON file can be overwritten each time.

- If you lose `$HIST`, the next download fetches everything again.
- The history is a plain list of Aura asset ids, one per line. To start one for a frame you downloaded before using this, make it from that download's JSON:
  ```bash
  python3 -c "import json,sys; print('\n'.join(a['id'] for a in json.load(open(sys.argv[1]))['assets']))" "$JSON" > "$HIST"
  ```
- In the app, tick "Skip photos downloaded before" for the same behavior. It keeps one history file per frame in `~/Library/Application Support/Aura Frame Downloader/history/`, separate from the command line's.
- If something goes wrong with steps 3 and 4, every rename and move is listed in `_rename_log.tsv` and `_move_log.tsv` in the folder (old path, then new path).

---

## Notes

- **Throttling:** The Aura API may throttle downloads. The script automatically waits between downloads, but you may need to restart it for large collections.

- **Resume support:** Already-downloaded photos are skipped, so you can safely restart the script. Without `--history` this only works while the files stay where they were downloaded.

- **Filename format:** `2012-04-15-03-15-04.000_B9A0E367-FA8D-4157-A090-7EE33F603312.jpeg`
  - Based on `taken_at` timestamp + unique `id` + original extension

- **Duplicates:** The same photo uploaded by different people will be downloaded separately. Consider running a duplicate finder afterward.

---

## Development

### macOS/Linux

```bash
# Install virtual environment with dependencies
make install

# Run the GUI
make run-gui

# Build macOS app
make build-mac

# Run linter
make lint
```

See `make help` for all available commands.

### Windows (PowerShell)

```powershell
# Full build (install + build)
.\build_windows.ps1 -All

# Or step by step:
.\build_windows.ps1 -Install    # Create venv and install dependencies
.\build_windows.ps1 -Build      # Build the executable
.\build_windows.ps1 -Run        # Run GUI from source
.\build_windows.ps1 -Clean      # Remove build artifacts
```

The built executable will be at `dist\Aura Downloader.exe`.
