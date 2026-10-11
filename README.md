# Mouse Scroll Direction

A small cross-platform GUI to set your mouse/touchpad scroll direction to
**Windows-style** or **Mac-style (natural)** with a single click.

Pick a direction, hit **Apply**.

- **Windows 10/11** — writes the HID `FlipFlopWheel` / `FlipFlopHScroll` registry
  values (auto-elevates to admin). Replug your mouse to take effect.
- **Raspberry Pi OS 2026 (Trixie) / labwc (Wayland)** — the default target. Writes
  `<naturalScroll>` into the per-user `~/.config/labwc/rc.xml` and reloads labwc.
  No admin needed, applies immediately.
- **GNOME (X11 or Wayland)** — uses `gsettings` (persistent).
- **Legacy X11** — installs a per-user autostart helper that runs `xinput`.

## How the two options feel

| Choice | Rolling the wheel **down** … |
|---|---|
| **Windows-style** | content scrolls **up** (the classic "bar" behaviour) |
| **Mac-style / natural** | content scrolls **down** (matches touchscreens & trackpads) |

## Requirements

Python 3 only — no third-party packages. The GUI uses Tk, which is usually included.

```bash
# Debian / Raspberry Pi OS, only if the Tk import fails
sudo apt install python3-tk
```

Optionally, depending on your desktop (all are optional — they're only used if
your desktop needs them): `gsettings` (GNOME), `xinput` (X11 fallback).

## Run it

```bash
python mouse_scroll.py          # Linux / macOS-hosted
pythonw mouse_scroll.py         # Windows (no console window)
# or simply:
python3 ./mouse_scroll.py

python3 mouse_scroll.py --check   # headless: report detected desktop + current setting
```

## Raspberry Pi OS 2026 (Trixie) notes

The default desktop is **labwc** (a Wayland/wlroots compositor), not GNOME and not
X11. The app targets this directly by editing the per-user labwc config:

- Location: `~/.config/labwc/rc.xml` (per-user; overrides the system default and
  survives package updates).
- The app adds/updates this block inside the config root and reloads labwc:

  ```xml
  <libinput>
    <device category="default"><naturalScroll>yes</naturalScroll></device>
  </libinput>
  ```

- `yes` = natural (Mac-style), `no` = traditional (Windows-style).
- `category="default"` applies to every pointing device (mouse **and** touchpad).
- Reloads immediately via `labwc --reconfigure`; if it ever doesn't take, log out/in.

> Tip: if things ever go wrong, just delete that file and re-run the app — it
> regenerates a clean one: `rm ~/.config/labwc/rc.xml`.

### Manual equivalent

```bash
mkdir -p ~/.config/labwc
$EDITOR ~/.config/labwc/rc.xml
```

Insert the `<libinput> … </libinput>` block above inside the root element
(`<labwc_config>`, or on a default Trixie install the self-closing
`<openbox_config …/>` — remove the trailing `/` so you can nest). Keep exactly
**one** `<?xml …?>` declaration on the first line; a second one breaks labwc's parser.

Reapply with `labwc --reconfigure`.

## Files

- `mouse_scroll.py` — the app (single file, cross-platform).
- `test_mouse_scroll.py` — unit tests for the labwc XML writer (`python3 test_mouse_scroll.py`).
- `MouseScroll.ps1` — the original Windows-only command-line variant (kept for
  convenience; the Python app already covers Windows).
- `mouse_scroll_info.txt` — quick install/run notes.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'tkinter'`** → `sudo apt install python3-tk`.
- **labwc: “error parsing config file”** → delete `~/.config/labwc/rc.xml` and re-run
  the app so it writes a clean file.
- **Windows: changes didn't stick** → run the app elevated (it prompts to elevate)
  and replug the mouse.
- **Want to see what's detected / which method would be used?** → run
  `python3 mouse_scroll.py --check` (headless, no GUI needed).
