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

Pick the block that matches the shell you opened — read your prompt:
`C:\Users\You>` is **cmd**; a `(PS) C:\...>` prompt or Windows 11's default
terminal is **PowerShell**. Don't mix the two.

**cmd (Command Prompt):**
```cmd
:: 1) download  (curl.exe exists on Windows 10+; the .exe spelling also works in PowerShell)
curl.exe -o %USERPROFILE%\Downloads\mouse_scroll.py -L https://raw.githubusercontent.com/RichardMidnight/MouseScroll/master/mouse_scroll.py
:: 2) run (prompts for admin once)
pythonw %USERPROFILE%\Downloads\mouse_scroll.py
```

**PowerShell:**
```powershell
# 1) download
Invoke-WebRequest https://raw.githubusercontent.com/RichardMidnight/MouseScroll/master/mouse_scroll.py -OutFile "$HOME\Downloads\mouse_scroll.py"
# 2) run (prompts for admin once)
pythonw "$HOME\Downloads\mouse_scroll.py"
```

Pick a direction and click **Apply**. That's it.

**Disposable** — your choice is saved where it belongs, so delete the file after:
Linux → `rm ~/Downloads/mouse_scroll.py`; Windows → `del %USERPROFILE%\Downloads\mouse_scroll.py` (cmd) or `Remove-Item $HOME\Downloads\mouse_scroll.py` (PowerShell).
(On Windows, wait a moment after Apply before deleting — it relaunches to apply.)

### Desktop menu entry (Linux, optional)

Make the app appear in the desktop menu — Settings/Preferences section of the
app menu, plus a right-click desktop menu item when labwc is the desktop:

```bash
python3 mouse_scroll.py install     # asks: [A]ll users, or this [U]ser only
python3 mouse_scroll.py uninstall   # removes whatever is installed (one confirm)
python3 mouse_scroll.py --check     # shows which scope is active (if any)
```

- **All users** (recommended; hit **enter** or `A`) → copies the script and the
  icon into `/usr/local` (needs `sudo`).
- **This user only** (`U`) → copies them into `~/.local`, no `sudo`.
- Only **one scope is active at a time** — installing one retires the other.
- `install -y` = all users, no prompts. `n`, EOF or Ctrl-C aborts with nothing changed.
- The menu entry runs the **copied** script, so the app still works even if you
  delete or move the file you downloaded.

## Raspberry Pi / labwc

The app edits the per-user `~/.config/labwc/rc.xml` (adds a `<libinput>` block with
`<naturalScroll>yes|no</naturalScroll>`) and reloads labwc. No admin needed; applies
now. If it ever parses wrong: `rm ~/.config/labwc/rc.xml` and re-run.

## Windows

Windows has **no Settings UI for mouse-wheel direction** — that's why your change
won't show up in *Settings → Bluetooth & devices → Mouse* (that page only offers
button swap, scroll speed, pointer speed). This tool instead writes the per-device
HID flags `FlipFlopWheel` / `FlipFlopHScroll`, which take effect when the device is
(re)plugged. The app itself is the state display: it reads the flag back and
pre-selects the matching radio.

There is one hidden gotcha. A separate **per-user** value can *also* flip the wheel
and fight the per-device flag above:

- `HKCU\Control Panel\Mouse\ReverseMouseWheelDirection` (DWORD)

If it's present and non-zero, and the per-device flag is set, the two can cancel
(each other or double-flip), depending on the raw hardware direction. Check for it:

```cmd
reg query "HKCU\Control Panel\Mouse" /v ReverseMouseWheelDirection
```

If it exists and is non-zero, set it to `0` so the tool's per-device flag is the
sole authority (this won't revert the app's per-device setting):

```cmd
reg add "HKCU\Control Panel\Mouse" /v ReverseMouseWheelDirection /t REG_DWORD /d 0 /f
```

## Files
- `mouse_scroll.py` — the app (single file).
- `mouse_scroll_icon.svg` — the menu icon (install copies it into the chosen scope).
- `test_mouse_scroll.py` — labwc XML-writer tests.
- `historical/` — superseded files (gitignored, not in the repo).

## Outstanding (known follow-ups, as of 2026-10-24)
- **The all-users (system) install has not been run on a real machine yet.**
  The sudo paths (`sudo install` into `/usr/local`, merge into
  `/etc/xdg/labwc/menu.xml`) were only verified against sandboxed paths.
  Exercise with: `install` → `A` → `uninstall` while watching the `/usr/local`
  and `/etc/xdg` artifacts.
- **The install-scope test suites are ephemeral** — `test_scopes.py` (20 checks)
  and `test_prereq.py` (7 scenarios) live in `/tmp/opencode/` (lost on reboot).
  Move them into the repo next to `test_mouse_scroll.py`.

## Troubleshooting
- `No module named 'tkinter'` → `sudo apt install python3-tk`
  (the app now detects this at launch and offers to install it for you).
- labwc "error parsing config" → delete `~/.config/labwc/rc.xml` and re-run.
- Windows changes not sticking → run elevated (it prompts) and replug the mouse.
- Windows direction feels **doubly inverted** (or Settings "doesn't reflect" it) →
  Settings has no wheel-direction control, so there's nothing to see there; check the
  hidden per-user flip instead — see the "Windows" section
  (`reg query "HKCU\Control Panel\Mouse" /v ReverseMouseWheelDirection`).
- Diagnose without the GUI → `python3 mouse_scroll.py --check` (also reports your
  Python version and whether it meets the 3.4 floor).
