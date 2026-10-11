# Mouse Scroll Direction

A small single-file Python GUI to set your mouse/touchpad scroll to
**Windows-style** or **Mac-style (natural)** with one click.

> **Beta** — early build; it may change or break. Back up before running.

## The two options

| You pick | Rolling the wheel **down** … |
|---|---|
| **Windows-style** | content scrolls **up** |
| **Mac-style / natural** | content scrolls **down** (like a trackpad) |

## Install & run

Single Python file, no `pip`. Needs **Python 3** + **Tkinter**
(usually bundled; on Debian / Raspberry Pi OS: `sudo apt install python3-tk`).

Works on **Windows 10/11** and **Linux** (Raspberry Pi OS 2026 / labwc is the
main target; GNOME and X11 work too). **macOS is not supported.**

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
- Diagnose without the GUI → `python3 mouse_scroll.py --check`.
