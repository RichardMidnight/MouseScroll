# Mouse Scroll Direction

A small single-file Python GUI to set your mouse/touchpad scroll to
**Windows-style** or **Mac-style (natural)** with one click.

> **Beta** — early build; it may change or break. Back up before running.

## The two options

| You pick | Rolling the wheel **down** … |
|---|---|
| **Windows-style** | content scrolls **up** |
| **Mac-style / natural** | content scrolls **down** (like a trackpad) |

## How it works

It detects your desktop, then writes your choice into the setting that controls
natural scrolling. What "Apply" does on each platform:

| Platform | How |
|---|---|
| **Raspberry Pi / labwc** | Adds a `<naturalScroll>yes/no</naturalScroll>` block to `~/.config/labwc/rc.xml`, then reloads labwc (`labwc --reconfigure` / `SIGHUP`). No admin. |
| **GNOME** | `gsettings set org.gnome.desktop.peripherals.{mouse,touchpad} natural-scroll <true/false>`. |
| **X11 (other)** | Installs a tiny per-user autostart helper that runs `xinput` at login. |
| **Windows** | Sets the HID `FlipFlopWheel` / `FlipFlopHScroll` values (prompts for admin). Replug the mouse. |

`yes`/`true` = Mac-style (natural); `no`/`false` = Windows-style. It edits the
**per-user** setting only — nothing in the system-wide config, so you can undo it by
re-running with the other option (or see "Raspberry Pi / labwc" to reset by hand).

## Install & run

Single Python file, no `pip`. Needs **Python 3.4+** and **Tkinter**
(usually bundled; on Debian / Raspberry Pi OS: `sudo apt install python3-tk`).
Kept simple so it still runs on old Linux, down to **Debian 8 (Jessie)**.

Works on **Windows 10/11** and **Linux** (Raspberry Pi OS 2026 / labwc is the
main target; GNOME and X11 work too). **macOS is not supported.**

On older Linux, which method applies depends on your desktop: **GNOME** →
`gsettings` (works from ~GNOME 3.14 / Jessie up — the reliable path on old
GNOME); **X11** → the `xinput` helper needs the libinput driver (Debian 9 /
Stretch+; a no-op on pre-libinput, evdev-era boxes); **labwc** → labwc hosts
only (Raspberry Pi OS 2026+).

It's a one-off: grab the file, run it from your **Downloads** folder, done.
(No terminal: in the repo, click **Download raw file** on `mouse_scroll.py`.)

### Linux
```bash
# 1) download
curl -fsSL https://raw.githubusercontent.com/RichardMidnight/MouseScroll/master/mouse_scroll.py -o ~/Downloads/mouse_scroll.py
# 2) run
python3 ~/Downloads/mouse_scroll.py
```

### Windows
```powershell
# 1) download
Invoke-WebRequest https://raw.githubusercontent.com/RichardMidnight/MouseScroll/master/mouse_scroll.py -OutFile "$HOME\Downloads\mouse_scroll.py"
# 2) run (prompts for admin once)
pythonw %USERPROFILE%\Downloads\mouse_scroll.py
```

Pick a direction and click **Apply**. That's it.

**Disposable** — your choice is saved where it belongs, so delete the file after:
Linux → `rm ~/Downloads/mouse_scroll.py`; Windows → `Remove-Item $HOME\Downloads\mouse_scroll.py`.
(On Windows, wait a moment after Apply before deleting — it relaunches to apply.)

## Raspberry Pi / labwc

The app edits the per-user `~/.config/labwc/rc.xml` (adds a `<libinput>` block with
`<naturalScroll>yes|no</naturalScroll>`) and reloads labwc. No admin needed; applies
now. If it ever parses wrong: `rm ~/.config/labwc/rc.xml` and re-run.

## Files
- `mouse_scroll.py` — the app (single file).
- `test_mouse_scroll.py` — labwc XML-writer tests.
- `historical/` — superseded files (gitignored, not in the repo).

## Troubleshooting
- `No module named 'tkinter'` → `sudo apt install python3-tk`.
- labwc "error parsing config" → delete `~/.config/labwc/rc.xml` and re-run.
- Windows changes not sticking → run elevated (it prompts) and replug the mouse.
- Diagnose without the GUI → `python3 mouse_scroll.py --check` (also reports your
  Python version and whether it meets the 3.4 floor).
