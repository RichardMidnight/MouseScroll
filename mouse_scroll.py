#!/usr/bin/env python3
# Cross-platform GUI to set mouse scroll direction to Windows-style or Mac-style (natural).
#
# Windows: requires admin to write HKLM (auto-elevates).
# Linux (order of preference):
#   1. labwc (default desktop on Raspberry Pi OS 2026 / Trixie, also wlroots/wayfire hosts)
#      -> write <naturalScroll> into the per-user ~/.config/labwc/rc.xml, then reload. No root needed.
#   2. GNOME (X11 or Wayland) -> gsettings (persistent, per-user).
#   3. X11 / other (legacy PIXEL, Openbox-X, generic X11 with libinput)
#      -> install a per-user autostart helper that runs xinput on login.
#
# Desktop menu (Linux) -- two scopes, only one active at a time:
#   python3 mouse_scroll.py install     -> ask: all users (recommended, /usr/local,
#                                         needs sudo) or this user (~/.local)
#                                         Then COPIES this .py + the icon into that
#                                         scope's home and adds the menu entry.
#   python3 mouse_scroll.py uninstall   -> removes whatever is installed (confirm)
#   (install -y = all users, no questions; uninstall -y skips its confirmation.)
#
# Prerequisites (tkinter, and xinput on X11-only boxes) are detected at launch;
# missing ones are offered for install (sudo apt ...) and installed on the spot,
# or installed without asking when -y / --yes is passed.
#
# NOTE: the old libinput *quirk* approach (AttrNaturalScrollEnabled) was removed because
# that is not a valid libinput model quirk; it is silently ignored. Natural scrolling is a
# libinput *runtime* setting, controlled per-compositor/DE as above.

import os
import re
import sys
import signal
import platform
import subprocess
import shutil
import stat

# tkinter powers the GUI, but the headless `--check` diagnostics don't need it,
# so a machine without python3-tk can still run `mouse_scroll.py --check`.
try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:
    tk = None
    messagebox = None

APP_TITLE = "Mouse Scroll Direction"
HELP_TEXT = "Choose your preferred scroll direction and click Apply."

# ---------------------- OS detection ----------------------
def is_windows():
    return platform.system() == "Windows"

def is_linux():
    return platform.system() == "Linux"

def cmd_exists(cmd):
    return shutil.which(cmd) is not None

# ---------------------- Windows helpers ----------------------
def is_admin_windows():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_windows(choice):
    # Relaunch self with admin rights, remembering which direction the user picked
    # (the elevated copy auto-applies it, so the first click takes effect).
    import ctypes
    flag = "--set-natural" if choice == "mac" else "--set-traditional"
    rest = [a for a in sys.argv[1:] if not a.startswith("--set-")] + [flag]
    params = " ".join(['"{}"'.format(p) for p in [sys.argv[0]] + rest])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        # ShellExecute returns >32 on success launch
        return rc > 32
    except Exception:
        return False

def _hid_device_parameter_keys():
    r"""
    Enumerate the paths of every "Device Parameters" key under HKLM
    SYSTEM\CurrentControlSet\Enum\HID (mouse, touchpads, docks, ...).
    Shared by the writer (windows_apply_scroll) and the reader
    (windows_flip_state); missing / unreadable branches are silently skipped.
    """
    try:
        import winreg
    except ImportError:
        return []
    keys = []

    def collect(root, subkey):
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
                if os.path.basename(subkey).lower() == "device parameters":
                    keys.append(subkey)
                i = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    collect(root, subkey + "\\" + child)
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hklm:
            collect(hklm, r"SYSTEM\CurrentControlSet\Enum\HID")
    except Exception:
        pass
    return keys

def windows_apply_scroll(natural: bool) -> bool:
    """
    Set FlipFlopWheel / FlipFlopHScroll across all HID Device Parameters.
    Verified on Win11 + a Microsoft HID mouse (045E:0737): flag=0 (the raw
    direction) is NATURAL scrolling (wheel down -> content down) and
    flag=1 (the flip) is standard Windows scrolling. So natural -> 0.
    If a machine ever behaves the other way around, its mouse's raw
    direction differs -- pick the other option, or flip this constant.
    Takes effect on replug / reconnect (the HID miniport reads it on attach).
    """
    try:
        import winreg
    except ImportError:
        messagebox.showerror(APP_TITLE, "winreg not available. Are you running Python for Windows?")
        return False

    if not is_admin_windows():
        ok = elevate_windows("mac" if natural else "windows")
        if ok:
            # Parent should exit so elevated child continues
            sys.exit(0)
        else:
            messagebox.showwarning(APP_TITLE, "Admin elevation failed. Try running as Administrator.")
            return False

    value = 0 if natural else 1
    wrote = False
    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hklm:
            for subkey in _hid_device_parameter_keys():
                try:
                    with winreg.OpenKey(hklm, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                        for name in ("FlipFlopWheel", "FlipFlopHScroll"):
                            try:
                                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                                wrote = True
                            except OSError:
                                pass
                except OSError:
                    continue
            return wrote
    except PermissionError:
        messagebox.showerror(APP_TITLE, "Permission denied writing registry. Run as Administrator.")
        return False

def windows_flip_state():
    """
    Read FlipFlopWheel from the first HID "Device Parameters" key that has one:
    0 = natural, 1 = traditional (verified mapping, see windows_apply_scroll).
    Returns None when no device ever had the flag set (nothing to guess from).
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hklm:
            for subkey in _hid_device_parameter_keys():
                try:
                    with winreg.OpenKey(hklm, subkey, 0, winreg.KEY_READ) as key:
                        v, _t = winreg.QueryValueEx(key, "FlipFlopWheel")
                        return int(v)
                except OSError:
                    continue
    except Exception:
        pass
    return None

# ---------------------- labwc helpers (Raspberry Pi OS 2026 / Trixie default) ----------------------
LABWC_HOME_RC = os.path.expanduser("~/.config/labwc/rc.xml")
LABWC_SYSTEM_RC = "/etc/xdg/labwc/rc.xml"

def labwc_active() -> bool:
    """
    True if we believe labwc is the running session (or at least installed).
    labwc itself exports LABWC_PID into the session environment, so that is the
    strongest signal; the config file / binary are fallbacks.
    """
    if os.environ.get("LABWC_PID"):
        return True
    if "labwc" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        return True
    return (cmd_exists("labwc")
            and (os.path.exists(LABWC_HOME_RC) or os.path.exists(LABWC_SYSTEM_RC)))

def labwc_reload() -> bool:
    """Best-effort: reload labwc's config so the change applies without a logout.

    Prefer signalling the running compositor via $LABWC_PID (SIGHUP) — that works
    without the labwc binary on PATH. Fall back to `labwc --reconfigure`."""
    pid = os.environ.get("LABWC_PID")
    if pid and pid.isdigit():
        try:
            os.kill(int(pid), signal.SIGHUP)
            return True
        except Exception:
            pass
    if not cmd_exists("labwc"):
        return False
    try:
        subprocess.check_call(["labwc", "--reconfigure"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=5)
        return True
    except Exception:
        return False

def _write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def _one_xml_declaration(s: str) -> str:
    """labwc (libxml2) rejects any XML declaration that is not the very first bytes.
    Collapse duplicate <?xml ...?> declarations down to a single one at the top."""
    decls = re.findall(r"<\?xml[^>]*\?>", s)
    if len(decls) <= 1:
        return s
    first = decls[0]
    rest = s
    for d in set(decls):      # remove every copy of each declaration
        rest = rest.replace(d, "")
    return first + "\n" + rest

def _is_well_formed(text: str) -> bool:
    """Best-effort well-formedness check (strict enough to catch a duplicate
    <?xml ...?> declaration or a stray nested root). Used to decide whether to
    rebuild a clean config instead of editing a broken one in place."""
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(text)
        return True
    except Exception:
        return False

def _libinput_block(natural: bool) -> str:
    val = "yes" if natural else "no"
    return (
        '  <libinput>\n'
        '    <device category="default"><naturalScroll>%s</naturalScroll></device>\n'
        '  </libinput>\n' % val
    )

def _device_line(natural: bool) -> str:
    val = "yes" if natural else "no"
    return '    <device category="default"><naturalScroll>%s</naturalScroll></device>\n' % val

def set_labwc(natural: bool) -> bool:
    """
    Set <naturalScroll> yes|no in the per-user labwc config (~/.config/labwc/rc.xml).

    Per-user is the recommended location: no root needed, it overrides the system file,
    and it is not clobbered by package updates. labwc is an Openbox fork, so the root
    element may be <labwc_config> *or* <openbox_config>; we handle both, including the
    default Raspberry Pi skeleton that is a single self-closing element:
        <openbox_config xmlns="http://openbox.org/3.4/rc"/>
    We use category="default", which applies to every pointing device (mouse + touchpad).
    """
    target = LABWC_HOME_RC
    DECL = '<?xml version="1.0"?>'
    try:
        raw = ""
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8") as f:
                raw = f.read()
        # Ensure the per-user labwc config directory exists (fresh installs don't
        # necessarily create ~/.config/labwc). Without this the first write raises.
        os.makedirs(os.path.dirname(target), exist_ok=True)

        block = _libinput_block(natural)

        # 0) A document that isn't well-formed XML can't be applied by labwc, so
        #    rather than flip a value inside a broken file, rebuild it cleanly.
        if raw.strip() and not _is_well_formed(raw):
            _write(target, DECL + "\n<labwc_config>\n" + block + "</labwc_config>\n")
            return True

        # 1) A well-formed file that already has a <naturalScroll> -> flip the value.
        if "<naturalScroll>" in raw:
            val = "yes" if natural else "no"
            out = re.sub(r"(<naturalScroll>)\s*(?:yes|no)\s*(</naturalScroll>)",
                         r"\g<1>" + val + r"\g<2>", raw)
            _write(target, _one_xml_declaration(out))
            return True


        # Recognized root? (<labwc_config> or <openbox_config>)
        root = re.search(r"<\s*(openbox_config|labwc_config)\b", raw)
        if not root:
            # 2) Fresh / no labwc root -> build a clean, minimal config.
            out = DECL + "\n<labwc_config>\n" + block + "</labwc_config>\n"
            _write(target, out)
            return True

        # 3) Existing root: rewrite cleanly around it, with exactly one XML declaration.
        body = _strip_decl(raw)
        rootname = root.group(1)

        # Merge into an existing <libinput> block if there is one.
        lib = re.search(r"<\s*libinput\b[^>]*>", body)
        if lib:
            body = body[:lib.end()] + "\n" + _device_line(natural) + body[lib.end():]
            _write(target, DECL + "\n" + body)
            return True

        # Open the root tag (self-closing <root .../> may need expanding).
        # Find the first '>' after the tag: attribute values don't contain a raw '>',
        # so the very next one ends the opening tag.
        open_re = re.search(r"<\s*(openbox_config|labwc_config)\b", body)
        rootname = open_re.group(1)
        gt = body.find(">", open_re.end())
        open_tag = body[open_re.start():gt + 1]
        if open_tag.endswith("/>"):
            body = body[:open_re.start()] + open_tag[:-2] + ">" + body[gt + 1:]

        # Insert the block right before the closing </root> tag.
        close = re.search(r"</\s*%s>" % re.escape(rootname), body)
        if close:
            body = body[:close.start()] + block + "</%s>" % rootname
        else:  # we just opened a self-closing root (or it had no close tag)
            body = body.rstrip() + "\n" + block + "</%s>" % rootname

        _write(target, DECL + "\n" + body)
        return True
    except PermissionError:
        return False
    except Exception:
        return False

def _strip_decl(s: str) -> str:
    """Return the text with any leading XML declaration removed (kept for re-adding)."""
    return re.sub(r"^[ \t\r\n]*<\?xml[^>]*\?>[ \t\r\n]*", "", s, count=1)

# ---------------------- GNOME (gsettings) helpers ----------------------
# The per-user GNOME schemas that carry the natural-scroll switch.
# Shared by linux_apply_via_gsettings (write) and detect_current_choice (read).
GNOME_NATURAL_SCROLL = (
    ("org.gnome.desktop.peripherals.mouse", "natural-scroll"),
    ("org.gnome.desktop.peripherals.touchpad", "natural-scroll"),
)

def linux_apply_via_gsettings(natural: bool) -> bool:
    """
    Use GNOME gsettings (persistent, per-user). Only meaningful when GNOME is the DE.
    """
    if not cmd_exists("gsettings"):
        return False

    val = "true" if natural else "false"
    any_set = False
    for schema, key in GNOME_NATURAL_SCROLL:
        # Verify schema/key exists
        try:
            subprocess.check_call(["gsettings", "get", schema, key],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        try:
            subprocess.check_call(["gsettings", "set", schema, key, val],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            any_set = True
        except subprocess.CalledProcessError:
            pass
    return any_set

# ---------------------- X11 fallback (autostart + xinput) ----------------------
HELPER_SCRIPT = """#!/usr/bin/env python3
import os, subprocess, shutil

def cmd_exists(c): return shutil.which(c) is not None

def set_xinput(natural: bool) -> bool:
    if not cmd_exists("xinput"):
        return False
    try:
        out = subprocess.check_output(["xinput", "list", "--short"], universal_newlines=True, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    updated = False
    ids = []
    for line in out.splitlines():
        low = line.lower()
        if ("pointer" in low) or ("mouse" in low) or ("touchpad" in low) or ("trackball" in low):
            for p in line.split():
                if p.startswith("id="):
                    ids.append(p.split("=",1)[1])
    prop = "libinput Natural Scrolling Enabled"
    for did in ids:
        try:
            props = subprocess.check_output(["xinput", "list-props", did], universal_newlines=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        if prop in props:
            try:
                subprocess.check_call(["xinput", "set-prop", did, prop, "1" if natural else "0"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                updated = True
            except subprocess.CalledProcessError:
                pass
    return updated

def main():
    natural = os.environ.get("MOUSE_NATURAL", "0") == "1"
    set_xinput(natural)

if __name__ == "__main__":
    main()
"""

def linux_install_autostart(natural: bool) -> bool:
    """
    Install a per-user autostart that enforces scroll direction on login (X11 only).
    Creates:
      ~/.local/bin/mouse_scroll_helper.py
      ~/.config/autostart/mouse_scroll_helper.desktop
    """
    try:
        home = os.path.expanduser("~")
        bin_dir = os.path.join(home, ".local", "bin")
        os.makedirs(bin_dir, exist_ok=True)
        helper_path = os.path.join(bin_dir, "mouse_scroll_helper.py")

        with open(helper_path, "w", encoding="utf-8") as f:
            f.write(HELPER_SCRIPT)
        st = os.stat(helper_path)
        os.chmod(helper_path, st.st_mode | stat.S_IEXEC)

        autostart_dir = os.path.join(home, ".config", "autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        desktop_path = os.path.join(autostart_dir, "mouse_scroll_helper.desktop")

        natural_env = "1" if natural else "0"
        desktop = ("[Desktop Entry]\n"
                   "Type=Application\n"
                   "Version=1.0\n"
                   "Name=Mouse Scroll Helper\n"
                   "Comment=Apply natural/traditional scrolling on login (X11)\n"
                   "Exec=env MOUSE_NATURAL=%s %s\n"
                   "X-GNOME-Autostart-enabled=true\n") % (natural_env, helper_path)
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop)
        return True
    except Exception as e:
        messagebox.showerror(APP_TITLE, "Failed to install autostart: %s" % e)
        return False

# ---------------------- Linux strategy ----------------------
_linux_last_method = None  # "labwc" | "gsettings" | "autostart" | None

def linux_apply_scroll(natural: bool) -> bool:
    """
    Try the method that actually drives natural scrolling on this desktop, in order:
      1) labwc  (Raspberry Pi OS 2026 / Trixie default)
      2) GNOME gsettings
      3) X11 autostart helper (xinput)
    """
    global _linux_last_method
    _linux_last_method = None

    if labwc_active() and set_labwc(natural):
        _linux_last_method = "labwc"
        labwc_reload()
        return True

    if linux_apply_via_gsettings(natural):
        _linux_last_method = "gsettings"
        return True

    if linux_install_autostart(natural):
        _linux_last_method = "autostart"
        return True

    return False

# ---------------------- Desktop menu install (Settings / Preferences, Linux) ----------------------
MENU_APP_ID = "com.mousescroll.MouseScroll"
# Markers so uninstall can remove exactly the item we added (and only the file
# we created may be deleted wholesale -- never a menu.xml the user wrote).
LABWC_ITEM_BEGIN = "<!-- mouse_scroll.py:begin -->"
LABWC_ITEM_END = "<!-- mouse_scroll.py:end -->"
LABWC_FILE_CREATED = "<!-- Created by mouse_scroll.py install (remove with: mouse_scroll.py uninstall) -->"
# Icon bundled next to this script; install copies it into the icon theme so
# both the app menu (.desktop) and labwc's item can resolve it by name.
MENU_ICON_NAME = "mouse_scroll_icon"
MENU_ICON_FALLBACK = "preferences-desktop-input"
MENU_ICON_SRC = os.path.join(os.path.dirname(os.path.abspath(os.path.realpath(__file__))), MENU_ICON_NAME + ".svg")
MENU_ICON_USER_FILE = os.path.expanduser(os.path.join("~/.local/share/icons/hicolor/scalable/apps", MENU_ICON_NAME + ".svg"))
# Two install scopes:
#   system -> /usr/local (FHS local add-ons, all users, needs sudo)
#             + the item in /etc/xdg/labwc/menu.xml
#   user   -> ~/.local (XDG user dirs, current user only, no sudo)
#             + the item in ~/.config/labwc/menu.xml
LABWC_MENU_SYSTEM_FILE = "/etc/xdg/labwc/menu.xml"
LABWC_MENU_USER_FILE   = os.path.expanduser("~/.config/labwc/menu.xml")
SCRIPT_BIN_NAME = "mouse_scroll.py"
SCOPES = ("system", "user")

def _scope_paths(scope):
    """Where the script, icon, .desktop entry and the labwc menu item live
    for a given install scope ('system' or 'user')."""
    if scope == "system":
        data, cfg, sudo = "/usr/local", "/etc/xdg", True
    else:
        data = os.path.expanduser("~/.local")
        cfg  = os.path.expanduser("~/.config")
        sudo = False
    return {
        "script":    os.path.join(data, "bin", SCRIPT_BIN_NAME),
        "icon":      os.path.join(data, "share", "icons", "hicolor", "scalable", "apps", MENU_ICON_NAME + ".svg"),
        "app_entry": os.path.join(data, "share", "applications", MENU_APP_ID + ".desktop"),
        "labwc_menu":os.path.join(cfg, "labwc", "menu.xml"),
        "sudo":      sudo,
    }

def _menu_exec_cmd(script_path=None) -> str:
    """sh command line that launches the GUI (quote the script path for spaces).
    script_path: the copy the menu should launch (defaults to this script)."""
    exe = sys.executable or "python3"
    script = script_path or os.path.abspath(os.path.realpath(__file__))
    return '%s "%s"' % (exe, script)

def _menu_desktop_entry(icon_names, exec_cmd=None) -> str:
    """Freedesktop .desktop file -> lands in the application menu's
    Settings/Preferences group (the wf-panel/pcmanfm start menu on Raspberry
    Pi OS 2026, the GNOME app grid, KDE, pcmanfm's menu, ...). `Settings;`
    matches every other settings app on this distro (rpcc, qt5ct, pi-packages).
    icon_names: icon names to try, first to last (Icon= supports a list)."""
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            "Name=Mouse Scroll Direction\n"
            "Comment=Set the mouse scroll direction to Windows-style or Mac-style\n"
            "Exec=%s\n" % (exec_cmd or _menu_exec_cmd())
            + "Icon=%s\n" % ",".join(dict.fromkeys(n for n in icon_names if n))
            + "Terminal=false\n"
            "Categories=Settings;Peripherals;\n"
            "Keywords=mouse;scroll;wheel;settings;preferences;\n")

def _labwc_menu_item(indent="  ", icon_name="preferences-desktop-input", exec_cmd=None) -> str:
    """The <item> block we add to labwc's static menu.xml (root-menu = the
    desktop right-click menu), wrapped in markers so uninstall can remove it.
    (labwc resolves a single icon name, so only the primary one goes here.)"""
    return (LABWC_ITEM_BEGIN + "\n"
            + indent + '<item label="Mouse Scroll Direction" icon="%s">\n' % icon_name
            + indent + '  <action name="Execute" command="%s" />\n' % (exec_cmd or _menu_exec_cmd())
            + indent + '</item>\n'
            + LABWC_ITEM_END + "\n")

def _menu_close_index(txt, open_tag_end) -> int:
    """Index of the '</menu>' closing the '<menu ...>' tag ending at
    open_tag_end, handling nested menus and self-closing references
    (<menu id="..."/> are common in root-menu)."""
    depth = 1
    i = open_tag_end
    open_re = re.compile(r"<\s*menu\b[^>]*?(/?)\s*>")
    close_re = re.compile(r"</\s*menu\s*>")
    while True:
        no = open_re.search(txt, i)
        nc = close_re.search(txt, i)
        if no and nc and no.start() < nc.start():
            if no.group(1) == "":
                depth += 1
            i = no.end()
        elif nc:
            depth -= 1
            if depth == 0:
                return nc.start()
            i = nc.end()
        else:
            return -1

def _labwc_menu_upstream(target):
    """The first menu.xml (other than `target` itself) labwc would find, in
    XDG search order. Only called when `target` doesn't exist yet, so the
    answer is the file we merge our item into."""
    dirs = []
    xdg = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg")
    home_cfg = os.path.expanduser("~/.config")
    for d in xdg.split(os.pathsep) + ["/usr/share"]:
        d = os.path.expanduser(d.strip())
        if d and d not in dirs:
            dirs.append(d)
    # the per-user file always shadows system ones for the end user; include it
    # first so a user-scope install that finds no system default still starts
    # from the user's own file when re-merging.
    for d in ([home_cfg] if home_cfg not in dirs else []) + dirs:
        p = os.path.join(d, "labwc", "menu.xml")
        if p != target and os.path.exists(p):
            return p
    return None

def _labwc_insert_item(base, icon_name="preferences-desktop-input", exec_cmd=None) -> str:
    """Insert our item into labwc's menu text: into the root-menu block if
    there is one, otherwise as a new root-menu before </openbox_menu>."""
    item = _labwc_menu_item("  ", icon_name, exec_cmd)
    open_re = re.search(r"<\s*menu\s+id=\"root-menu\"[^>]*>", base)
    if open_re:
        close = _menu_close_index(base, open_re.end())
        if close != -1:
            return base[:close] + item + base[close:]
    block = '\n  <menu id="root-menu">\n' + _labwc_menu_item("    ", icon_name, exec_cmd) + '  </menu>\n'
    m = re.search(r"</\s*openbox_menu\s*/>", base)
    if m:
        return base[:m.start()] + block + base[m.start():]
    # not even a closing </openbox_menu>: best effort at the end of the file
    return base.rstrip() + "\n" + block + "\n</openbox_menu>\n"

def labwc_merged_menu(menu_file, icon_name="preferences-desktop-input", exec_cmd=None):
    """(note, text): the full new content of `menu_file` including our item.
    Merges with the content already there (or, if the file doesn't exist, with
    the upstream menu.xml labwc would otherwise load), so existing items
    ("Desktop Preferences...", Terminal, Exit, ...) are preserved."""
    if os.path.exists(menu_file):
        with open(menu_file, "r", encoding="utf-8") as f:
            base = f.read()
        if LABWC_ITEM_BEGIN in base and LABWC_ITEM_END in base:
            # if the item is already there but its launch command no longer
            # matches (script moved), refresh that block in place
            if exec_cmd:
                seg = base[base.index(LABWC_ITEM_BEGIN):
                           base.index(LABWC_ITEM_END) + len(LABWC_ITEM_END)]
                if exec_cmd not in seg:
                    m = re.search(r"\n(\s*)<\s*item", seg)
                    fresh = _labwc_menu_item(m.group(1) if m else "  ", icon_name, exec_cmd)
                    return "updated launch command in %s" % menu_file, base.replace(seg, fresh, 1)
            return "item already present in %s" % menu_file, base
        note = "updated existing %s" % menu_file
    else:
        up = _labwc_menu_upstream(menu_file)
        if up:
            with open(up, "r", encoding="utf-8") as f:
                base = f.read()
            note = "created %s (merged with %s)" % (menu_file, up)
        else:
            base = "<?xml version='1.0' encoding='UTF-8'?>\n<openbox_menu>\n</openbox_menu>\n"
            note = "created %s (no upstream menu found)" % menu_file
    out = _labwc_insert_item(base, icon_name, exec_cmd)
    if note.startswith("created"):
        # mark files WE created, so uninstall can safely delete them wholesale
        # when they end up holding nothing else
        m = re.search(r"\n<\s*openbox_menu", out)
        if m:
            out = out[:m.start()] + "\n" + LABWC_FILE_CREATED + out[m.start():]
    return note, out

def labwc_install_menu_item(menu_file, icon_name="preferences-desktop-input",
                            exec_cmd=None, use_sudo=False) -> str:
    """Add the 'Mouse Scroll Direction' item to the labwc menu file
    (per-user or system scope). Idempotent. Returns a short note."""
    note, out = labwc_merged_menu(menu_file, icon_name, exec_cmd)
    if out is None or ("already present" in note):
        return note
    if use_sudo:
        if _sudo_write(out, menu_file) != 0:
            raise RuntimeError("could not write %s (sudo failed)" % menu_file)
    else:
        os.makedirs(os.path.dirname(menu_file), exist_ok=True)
        _write(menu_file, out)
    return note

def labwc_uninstall_menu_item(menu_file, use_sudo=False):
    """Remove our item from the labwc menu file; delete the file wholesale
    only if WE created it and no other menu items are left in it.
    Returns a short note, or None when there was nothing to remove."""
    if not os.path.exists(menu_file):
        return None
    with open(menu_file, "r", encoding="utf-8") as f:
        txt = f.read()
    if LABWC_ITEM_BEGIN not in txt:
        return None
    txt = re.sub(re.escape(LABWC_ITEM_BEGIN) + r"[\s\S]*?" + re.escape(LABWC_ITEM_END) + r"\s*",
                 "", txt)
    if LABWC_FILE_CREATED in txt and not re.search(r"<\s*item\b", txt):
        (_sudo_remove(menu_file) if use_sudo else os.remove(menu_file))
        return "deleted %s (created by install; nothing else in it)" % menu_file
    if use_sudo:
        if _sudo_write(txt, menu_file) != 0:
            raise RuntimeError("could not write %s (sudo failed)" % menu_file)
    else:
        _write(menu_file, txt)
    return "removed our item from %s (your other menu items kept)" % menu_file

def _labwc_menu_installed(menu_file) -> bool:
    """True if our item currently sits in the given labwc menu file."""
    if not os.path.exists(menu_file):
        return False
    try:
        with open(menu_file, "r", encoding="utf-8") as f:
            return LABWC_ITEM_BEGIN in f.read()
    except Exception:
        return False

# ---------------- Install scopes: all-users (/usr/local) vs current-user (~/.local) ----------------
def find_icon_source():
    """Where to copy the icon from: one next to this script, then a copy
    already installed in the user icon theme, then the system one. Running
    install from the installed copy (whose own dir has no .svg) still works."""
    cands = [
        MENU_ICON_SRC,
        os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/%s.svg" % MENU_ICON_NAME),
        "/usr/local/share/icons/hicolor/scalable/apps/%s.svg" % MENU_ICON_NAME,
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None

def _is_root() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False

def _sudo_run(args) -> int:
    """Run a command as root unless we already are (sudo's password prompt
    goes to the user's terminal; inherited stdin/tty)."""
    if not _is_root():
        args = ["sudo"] + args
    return subprocess.call(args)

def _sudo_copy(src, dst, mode="644") -> int:
    """Copy a file into place (creating parent dirs, system ownership)."""
    return _sudo_run(["install", "-D", "-m", mode, src, dst])

def _sudo_write(content, dst) -> int:
    """Write text to dst via a temp file so it ends up root-owned."""
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="mouse_scroll.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        rc = _sudo_run(["install", "-D", "-m", "644", tmp, dst])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return rc

def _sudo_remove(path) -> int:
    return _sudo_run(["rm", "-f", path])

def _sudo_can_do_work() -> bool:
    """Can we reach system scope at all: already root, a passwordless sudo,
    or an interactive terminal where sudo may prompt for the password."""
    if _is_root():
        return True
    if not cmd_exists("sudo"):
        return False
    if subprocess.call(["sudo", "-n", "true"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return True
    return sys.stdin.isatty()

def install_to_scope(scope) -> list:
    """Copy the script (+ the icon when one is available) and add the menu
    entries (application-menu .desktop, and the labwc desktop-menu item when
    labwc is this machine's desktop) at the given scope.
    Returns a list of human-readable notes; raises on hard failure."""
    p = _scope_paths(scope)
    notes = []
    script_src = os.path.abspath(os.path.realpath(__file__))

    # 1) the script itself -> <scope>/bin
    if p["sudo"]:
        if _sudo_copy(script_src, p["script"], "755") != 0:
            raise RuntimeError("could not install the script to %s (sudo failed)" % p["script"])
    else:
        os.makedirs(os.path.dirname(p["script"]), exist_ok=True)
        shutil.copyfile(script_src, p["script"])
        os.chmod(p["script"], 0o755)
    notes.append("installed script: %s" % p["script"])

    # 2) the icon -> <scope>'s hicolor theme, so menus resolve it by name
    icon_names = [MENU_ICON_FALLBACK]
    icsrc = find_icon_source()
    if icsrc:
        if p["sudo"]:
            _sudo_copy(icsrc, p["icon"], "644")
        else:
            os.makedirs(os.path.dirname(p["icon"]), exist_ok=True)
            shutil.copyfile(icsrc, p["icon"])
        icon_names.insert(0, MENU_ICON_NAME)
        notes.append("installed menu icon: %s" % p["icon"])

    # 3) the application-menu entry -> Settings/Preferences group
    entry = _menu_desktop_entry(icon_names, _menu_exec_cmd(p["script"]))
    if p["sudo"]:
        if _sudo_write(entry, p["app_entry"]) != 0:
            raise RuntimeError("could not write %s (sudo failed)" % p["app_entry"])
    else:
        os.makedirs(os.path.dirname(p["app_entry"]), exist_ok=True)
        with open(p["app_entry"], "w", encoding="utf-8") as f:
            f.write(entry)
    notes.append("wrote application-menu entry: %s" % p["app_entry"])

    # 4) labwc desktop (right-click) menu item, when labwc is the desktop
    if labwc_active():
        notes.append("labwc desktop menu: "
                     + labwc_install_menu_item(p["labwc_menu"], icon_names[0],
                                               _menu_exec_cmd(p["script"]), p["sudo"]))
        labwc_reload()
    return notes

def remove_scope(scope) -> list:
    """Remove the artifacts of a given scope (only the ones present).
    Returns notes about what was actually removed."""
    p = _scope_paths(scope)
    removed = []
    def drop(path, label):
        if not os.path.exists(path):
            return
        try:
            if p["sudo"]:
                if _sudo_remove(path) != 0:
                    raise RuntimeError("sudo rm failed")
            else:
                os.remove(path)
            removed.append("removed %s: %s" % (label, path))
        except Exception as e:
            print("Could not remove %s: %s" % (path, e))
    drop(p["script"], "script")
    drop(p["icon"], "menu icon")
    drop(p["app_entry"], "application-menu entry")
    try:
        note = labwc_uninstall_menu_item(p["labwc_menu"], p["sudo"])
        if note:
            removed.append(note)
            labwc_reload()
    except Exception as e:
        print("Could not update the labwc menu (%s)" % e)
    return removed

def _scope_installed(scope) -> bool:
    p = _scope_paths(scope)
    return (os.path.exists(p["script"])
            or os.path.exists(p["icon"])
            or os.path.exists(p["app_entry"])
            or _labwc_menu_installed(p["labwc_menu"]))

def _confirm(question, assume_yes) -> bool:
    """Ask for confirmation before touching the user's menu files.
    -y / --yes answers yes; an EOF'd or interrupted stdin answers no, so the
    command is safe to run inside scripts (it will not hang or auto-yes)."""
    if assume_yes:
        return True
    try:
        answer = input("%s [y/N] " % question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")

def ask_scope(assume_yes=False):
    """Which scope to install: 'system' (all users -- recommended) or 'user'.
    -y/--yes answers 'system' without asking; EOF or Ctrl-C answers None (= abort)."""
    if assume_yes:
        return "system"
    q = ("Install for [A]ll users (recommended, /usr/local, needs sudo) or "
         "this [U]ser only (~/.local)?\n"
         "A/U  (enter = all users, n = cancel): ")
    try:
        a = input(q).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if a in ("n", "no", "q", "quit", "c", "cancel", "abort"):
        return None
    if a in ("u", "user"):
        return "user"
    return "system"

def run_install(assume_yes=False) -> int:
    if not is_linux():
        print("Menu install is only supported on Linux")
        if is_windows():
            print("On Windows you don't need one -- just run:  python mouse_scroll.py  and click Apply.")
        return 1
    scope = ask_scope(assume_yes)
    if scope is None:
        print("Aborted -- nothing was changed.  (Pass -y or --yes to skip the question and install for all users.)")
        return 1
    if scope == "system" and not _sudo_can_do_work():
        print("Sudo is not available here; installing for the current user instead.")
        scope = "user"
    # keep exactly one scope active: retire the other one's artifacts first
    other = "user" if scope == "system" else "system"
    retired = remove_scope(other) if _scope_installed(other) else []
    try:
        notes = install_to_scope(scope)
    except Exception as e:
        print("Failed to install into the %s scope: %s" % (scope, e))
        return 1
    where = "all users" if scope == "system" else "the current user only"
    print('Installed "Mouse Scroll Direction" for %s:' % where)
    for n in retired:
        print("  (retired previous %s scope) - %s" % (other, n))
    for n in notes:
        print("  - %s" % n)
    print()
    print("Find it in the menu's Settings / Preferences section. You can also run it any time via:")
    print("  python3 %s" % _scope_paths(scope)["script"])
    return 0

def run_uninstall(assume_yes=False) -> int:
    if not is_linux():
        print("No menu entry to remove on this platform.")
        return 1
    if not _confirm("Remove \"Mouse Scroll Direction\" from the desktop menu (both the all-users and per-user copies)?", assume_yes):
        print("Aborted -- nothing was changed.  (Pass -y or --yes to skip the question.)")
        return 1
    removed = []
    for scope in SCOPES:
        removed.extend(remove_scope(scope))
    if not removed:
        print("Nothing was installed (no mouse-scroll menu entry found).")
        return 1
    print("Removed \"Mouse Scroll Direction\" from the desktop menu:")
    for n in removed:
        print("  - %s" % n)
    print("Your scroll *setting* itself is untouched.")
    return 0

# ---------------------- Detection (preselect radio button) ----------------------
def detect_current_choice() -> str:
    """
    Best-effort guess to preselect radio button. Returns "windows" or "mac".
    """
    # 0) Windows: the FlipFlop flag we (or other tooling) left on the HID devices.
    if is_windows():
        s = windows_flip_state()
        if s == 0:
            return "mac"
        if s == 1:
            return "windows"

    # 1) labwc rc.xml (per-user first, then system)
    for path in (LABWC_HOME_RC, LABWC_SYSTEM_RC):
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
            if re.search(r"<naturalScroll>\s*yes\s*</naturalScroll>", txt):
                return "mac"
            if re.search(r"<naturalScroll>\s*no\s*</naturalScroll>", txt):
                return "windows"
        except Exception:
            pass

    # 2) GNOME settings
    try:
        if is_linux() and cmd_exists("gsettings"):
            for schema, key in GNOME_NATURAL_SCROLL:
                out = subprocess.check_output(
                    ["gsettings", "get", schema, key],
                    universal_newlines=True, stderr=subprocess.DEVNULL
                ).strip()
                if out in ("true", "false"):
                    return "mac" if out == "true" else "windows"
    except Exception:
        pass

    # Default guess
    return "windows"

# ---------------------- GUI ----------------------
def fit_window(tk_root, min_w=460, min_h=220):
    """Grow the window so its current content all fits; never shrinks it.

    The window is non-resizable, so Tk won't grow it on its own when a label's
    text wraps to more lines (the status line after "Apply", or the expanded
    "More…" footer). We grow it explicitly, and only *up* (max with the current
    size) so it never snaps smaller and the layout stays put.
    """
    tk_root.update_idletasks()
    new_w = max(tk_root.winfo_width(),  min_w, tk_root.winfo_reqwidth())
    new_h = max(tk_root.winfo_height(), min_h, tk_root.winfo_reqheight())
    tk_root.geometry("%dx%d" % (new_w, new_h))

def apply_choice(choice_var, status):
    """Apply the chosen direction and report the result in the in-window status line.

    We intentionally do NOT open a separate pop-up here: on labwc/Wayland a Tk modal
    pop-up often opens *behind* the current window and doesn't raise/focus until you
    click it. Updating a label in the window that is already on top and focused is far
    more reliable. Green = success, red = a problem + what to do about it.
    """
    natural = (choice_var.get() == "mac")
    def ok(text):
        status.config(text=text, fg="#1a7f37")
        fit_window(status.winfo_toplevel())
    def bad(text):
        status.config(text=text, fg="#b42318")
        fit_window(status.winfo_toplevel())
    if is_windows():
        if windows_apply_scroll(natural):
            ok("Saved. Unplug and replug your mouse, or disable/enable it in Device Manager, "
               "for it to take effect. A reboot is rarely needed.")
        else:
            bad("Could not apply on Windows. Re-run as Administrator (right-click the script, "
                "choose \"Run as administrator\") so the setting can be saved.")
    elif is_linux():
        if linux_apply_scroll(natural):
            if _linux_last_method == "labwc":
                ok("Saved, and labwc is reloaded so it applies now. Give the wheel a few rolls "
                   "to confirm; if it still scrolls the old way, log out and back in.")
            elif _linux_last_method == "gsettings":
                ok("Saved to GNOME settings and kept across logins. You may need to log out and "
                   "back in to see it.")
            elif _linux_last_method == "autostart":
                ok("Saved as a per-user autostart (X11, via xinput). It re-applies on every "
                   "login; log out and back in to apply it now.")
            else:
                ok("Saved.")
        else:
            bad("Could not apply automatically. On Raspberry Pi OS, make sure the labwc desktop "
                "is in use (or the matching compositor/DE for your setup).")
    else:
        bad("Unsupported operating system: %s" % platform.system())

def env_label_text() -> str:
    if is_windows():
        return "Detected: Windows"
    if is_linux():
        if labwc_active():
            return "Detected: Linux / labwc (Wayland) — Raspberry Pi OS"
        if os.environ.get("WAYLAND_DISPLAY") or "wayland" in os.environ.get("XDG_SESSION_TYPE", "").lower():
            return "Detected: Linux / Wayland"
        return "Detected: Linux / X11"
    return "Detected: %s" % platform.system()

def run_check() -> int:
    """Headless diagnostics: report what we detected and what we'd apply.
    Runs without tkinter, so it's useful on a machine with no display."""
    def b(x):
        return "yes" if x else "no"
    print("=== mouse_scroll --check ===")
    print("OS          : %s %s" % (platform.system(), platform.release()))
    pyv = sys.version_info
    pys = ("OK (>= 3.4)" if (pyv.major, pyv.minor) >= (3, 4)
           else "below our 3.4 floor -- Debian 10 (Buster)+ ships 3.7; else install a newer python3")
    print("Python      : %d.%d.%d  [%s]" % (pyv.major, pyv.minor, pyv.micro, pys))
    if is_windows():
        print("Platform    : Windows")
        print("Would use   : Windows registry (FlipFlopWheel / FlipFlopHScroll)")
        cur = windows_flip_state()
        cur_text = {0: "natural / Mac-style",
                    1: "traditional / Windows-style"}.get(cur, "not set on any HID device")
        print("Current set : %s" % cur_text)
        missing = _missing_prerequisites()
        if missing:
            print("Prerequisites: MISSING: %s  (install the full Python from python.org -- it bundles tkinter)"
                  % ", ".join(label for label, _ in missing))
        else:
            print("Prerequisites: OK (tkinter present)")
    elif is_linux():
        print("Platform    : Linux")
        print("  labwc active : %s   (LABWC_PID=%s)" % (b(labwc_active()), os.environ.get("LABWC_PID", "-")))
        print("  home rc.xml  : %s exists=%s" % (LABWC_HOME_RC, b(os.path.exists(LABWC_HOME_RC))))
        print("  sys rc.xml   : %s exists=%s" % (LABWC_SYSTEM_RC, b(os.path.exists(LABWC_SYSTEM_RC))))
        print("  gsettings    : exists=%s" % b(cmd_exists("gsettings")))
        print("  xinput       : exists=%s" % b(cmd_exists("xinput")))
        if labwc_active():
            method = "labwc (rc.xml)"
        elif cmd_exists("gsettings"):
            method = "GNOME gsettings"
        else:
            method = "X11 autostart helper (xinput)"
        print("Would use   : %s" % method)
        cur = detect_current_choice()
        print("Current set : %s" % ("natural / Mac-style" if cur == "mac" else "traditional / Windows-style"))
        active = [s for s in SCOPES if _scope_installed(s)]
        if active:
            print("Menu entry  : installed (%s scope)" %
                  ", ".join("all users" if s == "system" else "this user" for s in active))
            p = _scope_paths(active[0])
            for k in ("script", "icon", "app_entry", "labwc_menu"):
                if os.path.exists(p[k]):
                    print("              %s: %s" % (k, p[k]))
        else:
            print("Menu entry  : not installed  (python3 mouse_scroll.py install)")
        missing = _missing_prerequisites()
        if missing:
            print("Prerequisites: MISSING: %s" % ", ".join(label for label, _ in missing))
            print("              install: sudo apt install %s" % " ".join(p for _, p in missing))
        else:
            print("Prerequisites: OK (tkinter present%s)" %
                  (", xinput present" if not labwc_active() and not cmd_exists("gsettings") else ""))
    else:
        print("Platform    : unsupported (%s)" % platform.system())
        missing = _missing_prerequisites()
        print("Prerequisites: %s" % ("MISSING: " + ", ".join(l for l, _ in missing) if missing else "OK"))
    print()
    print("Change it with the GUI:  python3 mouse_scroll.py")
    return 0

ALL_PLATFORM_FOOTER = (
    "Raspberry Pi OS 2026 (Trixie) / labwc:\n"
    "• Natural scroll via ~/.config/labwc/rc.xml — applies now, no admin needed.\n"
    "Other Linux: GNOME → gsettings; X11 → autostart helper (xinput).\n"
    "Windows: may request Admin."
)

def footer_text() -> str:
    """
    Short, context-aware footer line for the detected platform.
    The expanded all-platforms version sits behind the "More…" toggle.
    """
    if is_windows():
        return ("Saving needs Admin (it will ask). After Apply, unplug & replug the mouse "
                "for it to take effect.")
    if is_linux():
        if labwc_active():
            return "Applies immediately via ~/.config/labwc/rc.xml — no admin needed."
        if cmd_exists("gsettings"):
            return "GNOME: saved via gsettings. If it doesn't take effect, sign out and back in."
        if cmd_exists("xinput"):
            return "Other X11: saved as a per-user autostart (xinput); sign out/in to apply now."
        return "Linux: method detected at Apply time (labwc / GNOME / X11)."
    return "Not a supported platform — see the repo README."

# ---------------------- Prerequisites (detect + offer install) ----------------------
# tkinter drives the GUI (the "python3-tk" package on Debian/Ubuntu); xinput is
# only needed when the fallback legacy X11 path is what would be used.
def _missing_prerequisites():
    """[(label, apt-package), ...] for prerequisites that are required here
    but missing on this machine. Empty when everything is in place."""
    missing = []
    if tk is None:
        missing.append(("tkinter (GUI toolkit)", "python3-tk"))
    if is_linux():
        # xinput matters only when we'd fall through to the legacy X11 path,
        # i.e. neither labwc nor GNOME gsettings is available to apply the setting.
        if not cmd_exists("xinput") and not labwc_active() and not cmd_exists("gsettings"):
            missing.append(("xinput (legacy X11 scroll fallback)", "x11-xserver-utils"))
    return missing

def _reload_tkinter() -> bool:
    """After python3-tk has been installed, import tkinter again: the earlier
    import failure was transient and was not cached in sys.modules, so a fresh
    import now finds the module on disk."""
    global tk, messagebox
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
    except Exception:
        return False
    tk, messagebox = _tk, _mb
    return True

def ensure_prerequisites(assume_yes=False) -> bool:
    """Detect missing prerequisites (e.g. tkinter) and, if the user agrees,
    install them with apt. Returns True when everything needed is available.
    A dead/absent stdin declines the prompt, so scripts never hang here."""
    missing = _missing_prerequisites()
    if not missing:
        return True
    print("Missing prerequisites:")
    for label, pkg in missing:
        print("  - %-40s (package: %s)" % (label, pkg))
    if is_windows():
        print()
        print("This build of Python has no tkinter. Install the full Python distribution")
        print("from https://www.python.org/downloads/ (it bundles tkinter), then re-run.")
        return False
    if not cmd_exists("apt-get"):
        print()
        print("No apt on this system; install the listed packages with your package manager,")
        print("e.g.:  sudo apt install %s" % " ".join(p for _, p in missing))
        return False
    apt_cmd = ["sudo", "apt-get", "install", "-y"] + [p for _, p in missing]
    shown = "sudo apt install " + " ".join(p for _, p in missing)
    print()
    if not _confirm("Install them now?", assume_yes):
        print("Aborted -- nothing was installed.  You can install them at any time with:")
        print("  %s" % shown)
        return False
    rc = subprocess.call(apt_cmd)
    if rc != 0:
        print("Automatic install failed (sudo apt got rc=%d). Install manually:" % rc)
        print("  %s" % shown)
        return False
    if not _reload_tkinter():
        # tkinter was the missing piece and still cannot be imported in this process
        print("The packages installed but tkinter still will not load under this Python.")
        print("Re-run in a fresh terminal, or install manually:")
        print("  %s" % shown)
        return False
    if _missing_prerequisites():
        print("The prerequisites are still missing after the install. Install manually:")
        print("  %s" % shown)
        return False
    return True

def main():
    if not ensure_prerequisites(_yes_flag()):
        sys.exit(1)
    # If we were relaunched with a direction (see elevate_windows), that wins over detection:
    # it is the choice the user made on the window that elevated us.
    forced = None
    for a in sys.argv[1:]:
        if a == "--set-natural":
            forced = "mac"
        elif a == "--set-traditional":
            forced = "windows"

    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    root.minsize(460, 220)   # floor; the real size is computed after layout (below)

    frm = tk.Frame(root, padx=16, pady=16)
    frm.pack(fill="both", expand=True)

    tk.Label(frm, text=env_label_text(), fg="#666").pack(anchor="w", pady=(0, 6))
    tk.Label(frm, text=HELP_TEXT, justify="left", wraplength=440).pack(anchor="w", pady=(0, 10))

    choice_var = tk.StringVar()
    choice_var.set(forced if forced is not None else detect_current_choice())

    rb2 = tk.Radiobutton(frm, text="Natural scrolling (Mac-style)    wheel down = content scrolls down", variable=choice_var, value="mac")
    rb1 = tk.Radiobutton(frm, text="Traditional scrolling (Windows-style)    wheel down = content scrolls up", variable=choice_var, value="windows")
    rb2.pack(anchor="w")
    rb1.pack(anchor="w")

    status = tk.Label(frm, text="", wraplength=440, justify="left")

    btn = tk.Button(frm, text="Apply", command=lambda: apply_choice(choice_var, status))
    btn.pack(pady=16)
    status.pack(anchor="w")

    detail = {"on": False}
    def render_footer():
        foot.config(text=ALL_PLATFORM_FOOTER if detail["on"] else footer_text())
        more_btn.config(text="Less" if detail["on"] else "More…")
    def toggle_footer():
        detail["on"] = not detail["on"]
        render_footer()
        fit_window(frm.winfo_toplevel())

    foot = tk.Label(frm, text=footer_text(), fg="#8a8a8a", justify="left", wraplength=440)
    foot.pack(anchor="w")
    more_btn = tk.Button(frm, text="More…", relief="flat", bd=0, fg="#666",
                         command=toggle_footer, cursor="hand2")
    more_btn.pack(anchor="w", pady=(4, 0))

    # If this copy was launched elevated with the user's choice (see elevate_windows),
    # apply it right away: the window that asked for elevation has already left, so its
    # Apply click would be silently lost otherwise.
    if forced is not None and is_windows() and is_admin_windows():
        apply_choice(choice_var, status)

    # Size the window to its actual content so the footer and the "More…" button
    # are never clipped. Some window managers (e.g. labwc/Wayland) settle on a
    # smaller initial size, so we send an explicit, measured geometry request.
    # fit_window() is re-run after any change that can grow a label (the "Apply"
    # status line, the "More…" footer) in case that makes the window too short.
    fit_window(root)

    root.mainloop()

def _yes_flag() -> bool:
    return any(a in ("-y", "--yes") for a in sys.argv[1:])

if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(run_check())
    if "install" in sys.argv[1:]:
        sys.exit(run_install(_yes_flag()))
    if "uninstall" in sys.argv[1:]:
        sys.exit(run_uninstall(_yes_flag()))
    main()
