# Bramble

Search, download, sort into your own categories, and open films, shows, music, books and
games, all from one window.

## Download

- **Windows:** [Bramble-Windows.exe](https://github.com/paleLeap/bramble/releases/latest/download/Bramble-Windows.exe).
  Double-click it to start. Windows may say "Windows protected your PC" because Bramble
  is new and unsigned: click **More info**, then **Run anyway**.
- **Linux:** [Bramble-Linux.tar.gz](https://github.com/paleLeap/bramble/releases/latest/download/Bramble-Linux.tar.gz).
  Extract it and run `Bramble` inside the Bramble folder.

Every version is on the [releases page](https://github.com/paleLeap/bramble/releases).

## What it does

- **Categories** are folders in `MARROW` in your home folder; make them with the `+`.
- **Search** with the box at the bottom right. Add search sources by pasting a
  qBittorrent search plugin's address into the box; the leaf beside it switches each
  source on or off. Put "book" in a search to look in the free libraries first
  (archive.org library scans, Project Gutenberg).
- **Downloads** are checked before they join your library (nothing that can run hidden
  in a film, real video, a virus scan where the PC has one), then filed into the
  category you choose.
- **Opening** something uses the best program Bramble can find, and asks inside the
  window when there is more than one.

## Running from the source

Python 3 with PyQt6: `bash run.sh` (makes its own `.venv` the first time).

## Licence

GPL-3.0. See [LICENSE](LICENSE).
