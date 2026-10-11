#!/usr/bin/env python3
# Cross-platform GUI to set mouse scroll direction to Windows-style or Mac-style (natural)
# Windows: requires admin to write HKLM (auto-elevates).
# Linux: detects Wayland/X11.
#   - GNOME: gsettings (persistent)
#   - Wayland (e.g., Wayfire on Raspberry Pi OS Trixie): libinput quirk in /etc/libinput (needs pkexec/root)
#   - X11/other: autostart helper that runs xinput on login

import os
import sys
import platform
import subprocess
import shutil
import stat
import tkinter as tk
from tkinter import messagebox

APP_TITLE = "Mouse Scroll Direction"
HELP_TEXT = "Choose your preferred scroll direction and click Apply."

def is_windows():
    return platform.system() == "Windows"

def is_linux():
    return platform.system() == "Linux"

def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"

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

    wrote_any = False
    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hklm:
            wrote_any = recurse_set(hklm, base_path, 1 if natural else 0)
    except PermissionError:
        messagebox.showerror(APP_TITLE, "Permission denied writing registry. Run as Administrator.")
        return False

    return wrote_any

# ---------------------- Linux helpers ----------------------
def linux_apply_via_gsettings(natural: bool) -> bool:
    """
    Use GNOME gsettings (persistent, per-user).
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

# --- Wayland (libinput quirk) helpers ---
LIBINPUT_QUIRK_PATH = "/etc/libinput/local-overrides.quirks"

def libinput_quirk_content(natural: bool) -> str:
    # Affect mice; set to 1 for natural, 0 for traditional
    return f"""[NaturalScroll]
MatchUdevType=mouse
AttrNaturalScrollEnabled={'1' if natural else '0'}
"""

def write_root_file_with_pkexec(path: str, content: str) -> bool:
    """
    Write a root-owned file using pkexec. Returns True on success.
    """
    try:
        # If already root, write directly
        if os.geteuid() == 0:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        if not cmd_exists("pkexec"):
            return False

        # Use `install -D` to ensure directory exists and set mode
        cmd = ["pkexec", "sh", "-c", f"install -D -m 0644 /dev/stdin '{path}'"]
        proc = subprocess.run(cmd, input=content.encode("utf-8"),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc.returncode == 0
    except Exception:
        return False

def linux_apply_via_libinput_quirk(natural: bool) -> bool:
    """
    Wayland-friendly, system-wide setting via libinput quirk.
    """
    content = libinput_quirk_content(natural)
    ok = write_root_file_with_pkexec(LIBINPUT_QUIRK_PATH, content)
    return ok

# --- X11 fallback helper (your original autostart/xinput) ---
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
            parts = line.split()
            for p in parts:
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

def set_gsettings(natural: bool) -> bool:
    if not cmd_exists("gsettings"):
        return False
    val = "true" if natural else "false"
    schemas = [
        ("org.gnome.desktop.peripherals.mouse", "natural-scroll"),
        ("org.gnome.desktop.peripherals.touchpad", "natural-scroll"),
    ]
    any_set = False
    for schema, key in schemas:
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

def main():
    natural = os.environ.get("MOUSE_NATURAL", "0") == "1"
    # Prefer gsettings (persistent), then xinput (session)
    changed = set_gsettings(natural) or set_xinput(natural)
if __name__ == "__main__":
    main()
"""

def linux_install_autostart(natural: bool) -> bool:
    """
    Install a per-user autostart that enforces scroll direction on login.
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
        # make executable
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
Comment=Apply natural/traditional scrolling on login
Exec=env MOUSE_NATURAL={natural_env} {helper_path}
X-GNOME-Autostart-enabled=true
"""
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop)
        return True
    except Exception as e:
        messagebox.showerror(APP_TITLE, f"Failed to install autostart: {e}")
        return False

# Track how we applied (for better user messaging)
_linux_last_method = None  # "gsettings" | "libinput" | "autostart" | None

def linux_apply_scroll(natural: bool) -> bool:
    """
    Strategy:
      1) Try GNOME gsettings (if present)
      2) If Wayland: try libinput quirk (system-wide; requires pkexec/root)
      3) Else (X11/unknown): install autostart helper (xinput)
    """
    global _linux_last_method
    _linux_last_method = None

    if linux_apply_via_gsettings(natural):
        _linux_last_method = "gsettings"
        return True

    if is_wayland():
        if linux_apply_via_libinput_quirk(natural):
            _linux_last_method = "libinput"
            return True
        else:
            # If libinput failed (likely no pkexec / no permission), fall back to autostart
            if linux_install_autostart(natural):
                _linux_last_method = "autostart"
                return True
            return False
    else:
        if linux_install_autostart(natural):
            _linux_last_method = "autostart"
            return True
        return False

def detect_current_choice() -> str:
    """
    Best-effort guess to preselect radio button.
    Returns "windows" or "mac".
    """
    # 1) GNOME settings
    try:
        if is_linux() and cmd_exists("gsettings"):
            out = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.peripherals.mouse", "natural-scroll"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if out in ("true", "false"):
                return "mac" if out == "true" else "windows"
            out = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.peripherals.touchpad", "natural-scroll"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if out in ("true", "false"):
                return "mac" if out == "true" else "windows"
    except Exception:
        pass

    # 2) Wayland libinput quirk file
    if is_linux() and os.path.exists(LIBINPUT_QUIRK_PATH):
        try:
            with open(LIBINPUT_QUIRK_PATH, "r", encoding="utf-8") as f:
                txt = f.read()
            if "AttrNaturalScrollEnabled=1" in txt:
                return "mac"
            if "AttrNaturalScrollEnabled=0" in txt:
                return "windows"
        except Exception:
            pass

    # Default guess
    return "windows"

# ---------------------- GUI ----------------------
def apply_choice(choice_var, root):
    choice = choice_var.get()
    natural = (choice == "mac")
    if is_windows():
        ok = windows_apply_scroll(natural)
        if ok:
            msg = ("Applied! Unplug/replug your mouse (or disable/enable it in Device Manager) "
                   "to take effect. A reboot is rarely needed.")
            messagebox.showinfo(APP_TITLE, msg)
    elif is_linux():
        ok = linux_apply_scroll(natural)
        if ok:
            # Tailored message by method
            msg = None
            if _linux_last_method == "gsettings":
                msg = "Applied via GNOME settings (persistent). You may need to log out/in."
            elif _linux_last_method == "libinput":
                msg = ("Applied via libinput quirk in /etc/libinput (system-wide). "
                       "Log out/in or reboot for full effect.")
            elif _linux_last_method == "autostart":
                msg = ("Applied via per-user autostart helper (xinput). "
                       "It will enforce your choice on every login.")
            else:
                msg = "Applied."
            messagebox.showinfo(APP_TITLE, msg)
        else:
            if is_wayland() and not cmd_exists("pkexec"):
                messagebox.showwarning(
                    APP_TITLE,
                    ("Could not write /etc/libinput without privileges.\n\n"
                     "Install 'pkexec' (policykit-1) or run this app with sudo, "
                     "or keep using the autostart helper on X11.")
                )
            else:
                messagebox.showwarning(APP_TITLE, "Could not apply settings automatically.")
    else:
        messagebox.showerror(APP_TITLE, f"Unsupported OS: {platform.system()}")

def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    root.geometry("420x220")

    frm = tk.Frame(root, padx=16, pady=16)
    frm.pack(fill="both", expand=True)

    env_label = ""
    if is_linux():
        env_label = f"Detected: Linux / {'Wayland' if is_wayland() else 'X11'}"
    elif is_windows():
        env_label = "Detected: Windows"
    else:
        env_label = f"Detected: {platform.system()}"

    tk.Label(frm, text=env_label, fg="#666").pack(anchor="w", pady=(0,6))

    tk.Label(frm, text=HELP_TEXT, justify="left", wraplength=360).pack(anchor="w", pady=(0,10))

    choice_var = tk.StringVar()
    choice_var.set(detect_current_choice())

    rb1 = tk.Radiobutton(frm, text="Windows-style (down = page goes down)", variable=choice_var, value="windows")
    rb2 = tk.Radiobutton(frm, text="Mac-style / Natural (down = page goes up)", variable=choice_var, value="mac")
    rb1.pack(anchor="w")
    rb2.pack(anchor="w")

    btn = tk.Button(frm, text="Apply", command=lambda: apply_choice(choice_var, root))
    btn.pack(pady=16)

    foot = tk.Label(
        frm,
        text=("Linux:\n"
              "• GNOME → gsettings (persistent)\n"
              "• Wayland (e.g., Wayfire) → libinput quirk (/etc/libinput, requires pkexec/root)\n"
              "• X11/others → autostart helper (xinput)\n"
              "Windows: may request Admin."),
        fg="#666", justify="left", wraplength=380
    )
    foot.pack(anchor="w")

    root.mainloop()

if __name__ == "__main__":
    main()
