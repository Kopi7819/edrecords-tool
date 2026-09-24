# ED Records Tool

*Personal fan project -- not made by, endorsed by, or connected to Frontier Developments in any way.*

A desktop companion app for [Elite Dangerous](https://www.elitedangerous.com/) explorers. It reads your journal files as you play, compares what you've scanned against both your own personal bests and the community-wide records tracked on [EDAstro.com](https://edastro.com/), and helps you spot record-breaking discoveries as they happen -- plus tracks your exobiology (Codex/bioscan) progress.

## What it does

- **Current System** -- a live, auto-refreshing view of the system you're in: every body you've scanned, with your own best and the global (EDAstro) best for each tracked parameter, and a star (personal best) or diamond (beats the global record) marker on the matching value.
- **Body Records** -- browse your personal and global bests for every star/planet type you've ever tracked, independent of the system you're currently in, plus a "best overall regardless of subtype" view.
- **Body Matrix** -- a heatmap of star type x planet type: how many of each combination you've found, with Landable-only and Terraformable-only filters.
- **Bioscan Stats** -- a genus -> species -> color variant breakdown of every organism you've sampled, with "X / Y found" progress against the known total for each, and a voice + on-screen announcement whenever you scan something new.
- Optional spoken alerts, a persistent notification bar, and a dark, Elite-Dangerous-styled UI throughout.

## Requirements

- Python 3.11 or newer (developed and tested on 3.13)
- Windows (the default journal path assumes Windows; the app itself is pure Python/Tkinter and should run on other platforms if you point it at the right journal folder)
- An internet connection (for downloading EDAstro community records; the app works offline otherwise, just without global-record comparisons)

## Installation

### Option A: Download the ready-made .exe (no Python required)

Go to the [Releases page](../../releases) and download the latest `ED Records Tool.exe`. Put it in its own folder (it will create `settings.json`, `own_records.json`, and a `cache` folder next to itself the first time it runs), then just double-click it to run.

> **Note:** Windows Defender or your antivirus may flag the `.exe` or put it in quarantine the first time you run it. This is a well-known false positive with Python apps packaged this way (PyInstaller) -- it isn't unique to this project. If that happens and you'd rather not risk it, use Option B (running from source) instead, where you can read every line of code yourself.

### Option B: Run from source (requires Python)

1. **Install Python**, if you don't already have it: https://www.python.org/downloads/ (make sure to tick "Add Python to PATH" during setup).
2. **Download this project** -- either `git clone` the repository, or download it as a ZIP from GitHub and extract it somewhere on your computer.
3. **Open a terminal in the project folder** and install the required packages:
   ```
   pip install -r requirements.txt
   ```
4. **Run the app:**
   ```
   python gui.py
   ```

On first run, the app will look for your Elite Dangerous journal files at the standard location (`%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous`). If your journals live somewhere else (a network share, a different drive, etc.), open **Actions -> Settings...** in the app and set the correct path there.

The very first time it runs against a journal history, it needs to read through all of it to build your personal records -- this can take a little while for a long-established commander. You can also trigger this manually any time via **Actions -> Rebuild Own Records (full)**.

## Usage tips

- **Actions menu**: manually update from the journal, force-refresh EDAstro's cached data, pull the latest exobiology reference data (genus/species/variant counts), rebuild your records from scratch, or open Settings.
- **Voice alerts / Live auto-refresh** (top right, always visible): toggle spoken announcements and the 5-second auto-refresh cycle.
- Hover over a Global/Own Max/Min value in the Current System or Body Records tabs to see which body holds that record.
- Diagnostic/one-off analysis scripts live in a separate folder and aren't needed for normal use -- see its own notes if you're curious.

## Uninstalling

There's no installer and nothing is written outside the project folder -- no registry entries, no files elsewhere on disk. To remove the app, just delete the project folder. If you want to keep your data (e.g. to move it to a new folder) before deleting, back up:

- `own_records.json` -- your personal exploration records
- `settings.json` -- your configured journal path and preferences
- `cache/` -- downloaded EDAstro data (safe to discard; it'll just re-download)

To uninstall the Python packages this project used (only relevant if you ran it from source via Option B, and don't use these packages for anything else):
```
pip uninstall requests beautifulsoup4 pyttsx3
```

## Known limitations

- Sol Distance, Sagittarius A* Distance, Periapsis, and Semi-Major Axis aren't currently tracked from your own scans (EDAstro's global data for some of these is shown where available).
- System-level records (Body Count, ELW count, etc.) only track your own personal bests -- there's no global/EDAstro comparison for these yet, since EDAstro groups them by primary star type.
- The exobiology reference data (total known species/variants per genus) is a point-in-time snapshot; use **Actions -> Update Bio Reference Data** to refresh it if Frontier adds new species.

## Disclaimer

This project was built entirely through AI-assisted development with [Claude](https://claude.ai) (Anthropic) -- essentially all of the code, and this README, were written by Claude based on the author's requirements and feedback, not hand-written from scratch.

"Elite Dangerous" is a trademark of Frontier Developments plc. Nothing here is affiliated with, reviewed by, or backed by Frontier -- it's just a hobby project by a player. No game artwork, audio, or other copyrighted assets are bundled with or distributed by this project; it works entirely by reading the plain-text journal log files the game writes to your disk for third-party tools to consume (the same approach used by tools like EDMC and EDDiscovery), plus publicly available community stats fetched from EDAstro.com.

This software is provided "as is", without warranty of any kind. The author accepts no responsibility or liability for any damage, data loss, or other issues arising from downloading, installing, or using this program. Use at your own risk. See [LICENSE](LICENSE) for the full legal terms.

## License

MIT -- see [LICENSE](LICENSE).
