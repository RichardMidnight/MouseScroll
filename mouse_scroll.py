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

def elevate_windows():
    # Relaunch self with admin rights
    import ctypes
    params = " ".join(['"{}"'.format(p) for p in sys.argv])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        # ShellExecute returns >32 on success launch
        return rc > 32
    except Exception:
        return False

def windows_apply_scroll(natural: bool) -> bool:
    """
    Set FlipFlopWheel / FlipFlopHScroll = 1 (natural) or 0 (windows) across all HID Device Parameters.
    """
    try:
        import winreg
    except ImportError:
        messagebox.showerror(APP_TITLE, "winreg not available. Are you running Python for Windows?")
        return False

    if not is_admin_windows():
        ok = elevate_windows()
        if ok:
            # Parent should exit so elevated child continues
            sys.exit(0)
        else:
            messagebox.showwarning(APP_TITLE, "Admin elevation failed. Try running as Administrator.")
            return False

    base_path = r"SYSTEM\CurrentControlSet\Enum\HID"

    def recurse_set(root, subkey, value_to_set):
        wrote = False
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                if os.path.basename(subkey).lower() == "device parameters":
                    for name in ("FlipFlopWheel", "FlipFlopHScroll"):
                        try:
                            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value_to_set))
                            wrote = True
                        except OSError:
                            pass
                # Recurse
                i = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, i)
                        i += 1
                        if recurse_set(root, subkey + "\\" + child, value_to_set):
                            wrote = True
                    except OSError:
                        break
        except FileNotFoundError:
            pass
        except PermissionError:
            pass
        return wrote

    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hklm:
            return recurse_set(hklm, base_path, 1 if natural else 0)
    except PermissionError:
        messagebox.showerror(APP_TITLE, "Permission denied writing registry. Run as Administrator.")
        return False

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
        proc = subprocess.run(["labwc", "--reconfigure"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return proc.returncode == 0
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
def linux_apply_via_gsettings(natural: bool) -> bool:
    """
    Use GNOME gsettings (persistent, per-user). Only meaningful when GNOME is the DE.
    """
    if not cmd_exists("gsettings"):
        return False

    val = "true" if natural else "false"
    schemas = [
        ("org.gnome.desktop.peripherals.mouse", "natural-scroll"),
        ("org.gnome.desktop.peripherals.touchpad", "natural-scroll"),
    ]
    any_set = False
    for schema, key in schemas:
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
        out = subprocess.check_output(["xinput", "list", "--short"], text=True, stderr=subprocess.DEVNULL)
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
            props = subprocess.check_output(["xinput", "list-props", did], text=True, stderr=subprocess.DEVNULL)
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
        desktop = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Mouse Scroll Helper
Comment=Apply natural/traditional scrolling on login (X11)
Exec=env MOUSE_NATURAL={natural_env} {helper_path}
X-GNOME-Autostart-enabled=true
"""
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop)
        return True
    except Exception as e:
        messagebox.showerror(APP_TITLE, f"Failed to install autostart: {e}")
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

# ---------------------- Detection (preselect radio button) ----------------------
def detect_current_choice() -> str:
    """
    Best-effort guess to preselect radio button. Returns "windows" or "mac".
    """
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
            for schema in ("org.gnome.desktop.peripherals.mouse",
                           "org.gnome.desktop.peripherals.touchpad"):
                out = subprocess.check_output(
                    ["gsettings", "get", schema, "natural-scroll"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                if out in ("true", "false"):
                    return "mac" if out == "true" else "windows"
    except Exception:
        pass

    # Default guess
    return "windows"

# ---------------------- GUI ----------------------
def apply_choice(choice_var, root):
    choice = choice_var.get()
    natural = (choice == "mac")
    state = ("Natural scrolling (Mac-style)\nwheel down = content scrolls down"
             if natural else
             "Traditional scrolling (Windows-style)\nwheel down = content scrolls up")
    head = "Scroll direction set to: %s" % state
    if is_windows():
        ok = windows_apply_scroll(natural)
        if ok:
            msg = ("Applied! Unplug/replug your mouse (or disable/enable it in Device Manager) "
                   "to take effect. A reboot is rarely needed.")
            messagebox.showinfo(APP_TITLE, head + "\n\n" + msg)
    elif is_linux():
        ok = linux_apply_scroll(natural)
        if ok:
            if _linux_last_method == "labwc":
                msg = ("Applied to labwc (Raspberry Pi OS / Trixie). It is being applied now;\n"
                       "if your wheel still scrolls the same way, log out and back in.")
            elif _linux_last_method == "gsettings":
                msg = "Applied via GNOME settings (persistent). You may need to log out/in."
            elif _linux_last_method == "autostart":
                msg = ("Applied via per-user autostart helper (xinput, X11).\n"
                       "It will enforce your choice on every login.")
            else:
                msg = "Applied."
            messagebox.showinfo(APP_TITLE, head + "\n\n" + msg)
        else:
            messagebox.showwarning(APP_TITLE,
                                   "Could not apply settings automatically.\n"
                                   "On Raspberry Pi OS, make sure the labwc desktop is in use.")
    else:
        messagebox.showerror(APP_TITLE, f"Unsupported OS: {platform.system()}")

def env_label_text() -> str:
    if is_windows():
        return "Detected: Windows"
    if is_linux():
        if labwc_active():
            return "Detected: Linux / labwc (Wayland) — Raspberry Pi OS"
        if os.environ.get("WAYLAND_DISPLAY") or "wayland" in os.environ.get("XDG_SESSION_TYPE", "").lower():
            return "Detected: Linux / Wayland"
        return "Detected: Linux / X11"
    return f"Detected: {platform.system()}"

def run_check() -> int:
    """Headless diagnostics: report what we detected and what we'd apply.
    Runs without tkinter, so it's useful on a machine with no display."""
    def b(x):
        return "yes" if x else "no"
    print("=== mouse_scroll --check ===")
    print("OS          : %s %s" % (platform.system(), platform.release()))
    if is_windows():
        print("Platform    : Windows")
        print("Would use   : Windows registry (FlipFlopWheel / FlipFlopHScroll)")
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
    else:
        print("Platform    : unsupported (%s)" % platform.system())
    print()
    print("Change it with the GUI:  python3 mouse_scroll.py")
    return 0

def main():
    if tk is None:
        sys.stderr.write("tkinter is not available. Install it, e.g.:\n  sudo apt install python3-tk\n")
        sys.exit(1)
    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    root.minsize(460, 220)   # window sizes to content; the footer won't be clipped

    frm = tk.Frame(root, padx=16, pady=16)
    frm.pack(fill="both", expand=True)

    tk.Label(frm, text=env_label_text(), fg="#666").pack(anchor="w", pady=(0, 6))
    tk.Label(frm, text=HELP_TEXT, justify="left", wraplength=440).pack(anchor="w", pady=(0, 10))

    choice_var = tk.StringVar()
    choice_var.set(detect_current_choice())

    rb1 = tk.Radiobutton(frm, text="Traditional scrolling (Windows-style)    wheel down = content scrolls up", variable=choice_var, value="windows")
    rb2 = tk.Radiobutton(frm, text="Natural scrolling (Mac-style)    wheel down = content scrolls down", variable=choice_var, value="mac")
    rb1.pack(anchor="w")
    rb2.pack(anchor="w")

    btn = tk.Button(frm, text="Apply", command=lambda: apply_choice(choice_var, root))
    btn.pack(pady=16)

    foot = tk.Label(
        frm,
        text=("Raspberry Pi OS 2026 (Trixie) / labwc:\n"
              "• Natural scroll via ~/.config/labwc/rc.xml — applies now, no admin needed.\n"
              "Other Linux: GNOME → gsettings; X11 → autostart helper (xinput).\n"
              "Windows: may request Admin."),
        fg="#666", justify="left", wraplength=440
    )
    foot.pack(anchor="w")

    root.mainloop()

if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(run_check())
    main()
