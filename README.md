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

## Install & run

It's a **single Python file** — no `pip`, no build, no third-party packages. You
just need **Python 3** and **Tkinter** (bundled into normal Python builds; on
Debian / Raspberry Pi OS, if `import tkinter` ever fails, run
`sudo apt install python3-tk`).

**Works on** Windows 10/11 and Linux (Raspberry Pi OS 2026 / labwc is the main
target; GNOME and legacy X11 are handled too). **macOS is not supported.**

### 1) Get just the one file (no cloning needed)

- **No terminal:** in your GitHub repo, open `mouse_scroll.py` and click the
  **Download raw file** button. That one file is all you need.
- **Linux / Raspberry Pi:**
```bash
curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/mouse_scroll.py -o ~/mouse_scroll.py
```
- **Windows (PowerShell):**
```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/USER/REPO/main/mouse_scroll.py" -OutFile "$HOME\mouse_scroll.py"
```
> Replace `USER/REPO` (and `main`, if your default branch differs) with your
> GitHub username and repo name.

### 2) Run it

```bash
python3 ~/mouse_scroll.py              # Linux / Raspberry Pi
pythonw %USERPROFILE%\mouse_scroll.py  # Windows (no console window)
```

Pick **Windows-style** or **Mac-style (natural)** and click **Apply**. That's it.

### 3) It's disposable — safe to delete the file afterwards

The script saves your choice where it belongs, so the file itself isn't needed
once applied:

- Raspberry Pi / labwc → `~/.config/labwc/rc.xml`
- GNOME → `gsettings` (per-user, `org.gnome.desktop.peripherals.*`)
- X11 → a small per-user autostart helper in `~/.local/bin/`
- Windows → the mouse's HID `FlipFlop*` registry values

So delete it any time (`rm ~/mouse_scroll.py`, or `Remove-Item $HOME\mouse_scroll.py`).
To change it later, just run it again — re-download the file first if you deleted it.
*On Windows, “Apply” relaunches the file elevated, so keep it until the change has
taken effect; on Linux you can remove it right away.*

### For contributors

```bash
git clone https://github.com/USER/REPO && cd REPO     # only needed to work on it / test
python3 test_mouse_scroll.py        # run the labwc XML-writer tests
python3 mouse_scroll.py --check     # headless: show detected desktop + current setting
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
- `historical/` — superseded files (gitignored, not in the repo):
  `mouse_scroll_info.txt` (the original quick-notes doc, now covered by this
  README), `MouseScroll.ps1` (the old Windows-only CLI), and `mouse_scroll_2.py`
  (an earlier revision). The Python app covers everything these did.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'tkinter'`** → `sudo apt install python3-tk`.
- **labwc: “error parsing config file”** → delete `~/.config/labwc/rc.xml` and re-run
  the app so it writes a clean file.
- **Windows: changes didn't stick** → run the app elevated (it prompts to elevate)
  and replug the mouse.
- **Want to see what's detected / which method would be used?** → run
  `python3 mouse_scroll.py --check` (headless, no GUI needed).
