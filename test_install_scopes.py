#!/usr/bin/env python3
"""Install-scope engine tests for mouse_scroll.py.

Runs with a sandboxed HOME (the real $HOME and the live labwc session are
never touched). The "system" scope is redirected to a fake tree on local disk,
so the sudo paths are exercised as plain file writes.
"""
import builtins
import importlib.util
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SB = tempfile.mkdtemp(prefix="mouse_scroll_scope_test.")
os.environ["HOME"] = SB
os.environ.pop("LABWC_PID", None)
os.environ.pop("XDG_CONFIG_DIRS", None)

spec = importlib.util.spec_from_file_location("ms", os.path.join(HERE, "mouse_scroll.py"))
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)
ms.labwc_active = lambda: False   # keep the tests off the live labwc session
ms.labwc_reload = lambda: None
ms._sudo_can_do_work = lambda: True

def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    print("ok  -", msg)

up = lambda p: os.path.expanduser(p)
FAKE = {
    "script":    SB + "/fake_system/bin/mouse_scroll.py",
    "icon":      SB + "/fake_system/icons/mouse_scroll_icon.svg",
    "app_entry": SB + "/fake_system/applications/com.mousescroll.MouseScroll.desktop",
    "labwc_menu":SB + "/fake_xdg/labwc/menu.xml",
    "sudo":      False,
}
_real_scope_paths = ms._scope_paths
real_user = dict(_real_scope_paths("user"))
ms._scope_paths = lambda scope: FAKE if scope == "system" else dict(real_user)

# ---------------- ask_scope ----------------
def feed(*lines):
    buf = io.StringIO("".join(l + "\n" for l in lines))
    return lambda prompt="": buf.readline().rstrip("\n")

eof = lambda p="": (_ for _ in ()).throw(EOFError)

def with_input(input_fn, fn, *a):
    bi = builtins.input
    builtins.input = input_fn
    try:
        return fn(*a)
    finally:
        builtins.input = bi

cases = [
    (True,  feed(),          "system"),   # -y
    (False, feed("u"),       "user"),
    (False, feed("U"),       "user"),
    (False, feed("user"),    "user"),
    (False, feed("a"),       "system"),
    (False, feed(""),        "system"),   # enter = all users
    (False, feed("yes"),     "system"),
    (False, feed("n"),       None),
    (False, feed("no"),      None),
    (False, eof,             None),
]
for assume, fi, want in cases:
    got = with_input(fi, ms.ask_scope, assume)
    check(got == want, "ask_scope(assume=%r) -> %r (want %r)" % (assume, got, want))

# ---------------- user-scope install end-to-end ----------------
rc = with_input(feed("u"), ms.run_install, False)
check(rc == 0, "install answered 'u' -> rc 0 (got %r)" % rc)
p = ms._scope_paths("user")
check(os.path.exists(p["script"]), "user script copied")
mode = os.stat(p["script"]).st_mode & 0o777
check(mode == 0o755, "user script is 0755 (got %o)" % mode)
check(os.path.exists(p["icon"]), "user icon copied")
check(os.path.exists(p["app_entry"]), "user .desktop written")
desk = open(p["app_entry"]).read()
check(("Exec=" + ms._menu_exec_cmd(p["script"])) in desk, "Exec points at the installed copy")
check("Icon=mouse_scroll_icon,preferences-desktop-input" in desk, "icon list with fallback")
check("Categories=Settings;Peripherals;" in desk, "Settings category")

# ---------------- re-run is idempotent ----------------
with_input(feed("u"), ms.run_install, False)
check(open(p["app_entry"]).read() == desk, "re-install leaves .desktop unchanged")

# ---------------- switching scopes retires the other ----------------
rc = with_input(feed("a"), ms.run_install, False)   # all users = system (fake)
check(rc == 0, "install answered 'a' -> rc 0")
check(os.path.exists(FAKE["script"]) and os.path.exists(FAKE["app_entry"]),
      "system (fake) artifacts present")
check(not os.path.exists(p["script"]), "user script retired")
check(not os.path.exists(p["icon"]), "user icon retired")
check(not os.path.exists(p["app_entry"]), "user .desktop retired")

rc = with_input(feed("u"), ms.run_install, False)   # back to user
check(rc == 0 and os.path.exists(p["script"]) and os.path.exists(p["icon"]), "user scope back")
check(not os.path.exists(FAKE["script"]) and not os.path.exists(FAKE["app_entry"]),
      "system (fake) artifacts retired")

# ---------------- uninstall sweeps both scopes ----------------
os.makedirs(os.path.dirname(FAKE["app_entry"]), exist_ok=True)
open(FAKE["app_entry"], "w").write("[Desktop Entry]\n")
rc = with_input(feed("y"), ms.run_uninstall, False)
check(rc == 0, "uninstall after both present -> rc 0")
check(not os.path.exists(p["script"]) and not os.path.exists(FAKE["app_entry"]),
      "no artifacts remain")

# ---------------- uninstall when nothing installed ----------------
check(ms.run_uninstall(True) == 1, "uninstall with nothing installed -> rc 1")

# ---------------- install abort leaves nothing behind ----------------
check(with_input(feed("n"), ms.run_install, False) == 1, "install answered 'n' -> rc 1")
check(with_input(eof, ms.run_install, False) == 1, "install answer EOF -> rc 1")
check(not os.path.exists(p["script"]) and not os.path.exists(FAKE["script"]),
      "aborted install left nothing behind")

# ---------------- labwc merge preserves other items; uninstall clean ----------------
menu = SB + "/user_config/labwc/menu.xml"
os.makedirs(os.path.dirname(menu), exist_ok=True)
open(menu, "w").write(
    "<?xml version='1.0' encoding='UTF-8'?>\n<openbox_menu>\n  <menu id=\"root-menu\">\n"
    "    <item label=\"Desktop Preferences...\" icon=\"preferences-system\">\n"
    '      <action name="Execute" command="desktop_preferences" />\n    </item>\n'
    "  </menu>\n</openbox_menu>\n")
note, text = ms.labwc_merged_menu(menu, "mouse_scroll_icon", 'python3 "/x/mouse_scroll.py"')
check("Desktop Preferences..." in text and ms.LABWC_ITEM_BEGIN in text,
      "merge keeps other items, adds ours")
open(menu, "w").write(text)                      # labwc_install would write this
note2, text2 = ms.labwc_merged_menu(menu, "mouse_scroll_icon", 'python3 "/x/mouse_scroll.py"')
check("already present" in note2 and text2 == text, "merge idempotent (item already in file)")
note3, text3 = ms.labwc_merged_menu(menu, "mouse_scroll_icon", 'python3 "/NEW/mouse_scroll.py"')
check("updated launch command" in note3 and '"/NEW/mouse_scroll.py"' in text3
      and "Desktop Preferences..." in text3, "stale launch command refreshed in place")
open(menu, "w").write(text3)
got = ms.labwc_uninstall_menu_item(menu, False)
after = open(menu).read() if os.path.exists(menu) else ""
check(got and ms.LABWC_ITEM_BEGIN not in after and "Desktop Preferences..." in after,
      "labwc uninstall removed only our item, kept the rest")

# ---------------- no root-menu: new block appended; round-trips ----------------
menu2 = SB + "/menu2.xml"
open(menu2, "w").write(
    "<?xml version='1.0' encoding='UTF-8'?>\n<openbox_menu>\n"
    '  <item label="Terminal" icon="utilities-terminal"/>\n</openbox_menu>\n')
n, t = ms.labwc_merged_menu(menu2, "i", "python3 /x/m")
check('<menu id="root-menu">' in t and "Terminal" in t,
      "insert builds a root-menu when none exists")
open(menu2, "w").write(t)
got = ms.labwc_uninstall_menu_item(menu2, False)
t = open(menu2).read()
check(got and ms.LABWC_ITEM_BEGIN not in t and "Terminal" in t, "uninstall round-trip ok")

# ---------------- created file carries marker; wholesale delete allowed ----------------
menu3 = SB + "/menu3.xml"
_orig_upstream = ms._labwc_menu_upstream
ms._labwc_menu_upstream = lambda target: None    # no upstream: skeleton only
n, t = ms.labwc_merged_menu(menu3, "i", "python3 /x/m")
ms._labwc_menu_upstream = _orig_upstream
check(ms.LABWC_FILE_CREATED in t, "file we create carries the created-marker")
open(menu3, "w").write(t)
got = ms.labwc_uninstall_menu_item(menu3, False)
check("deleted" in got and not os.path.exists(menu3),
      "created empty-of-rest menu deleted wholesale")

shutil.rmtree(SB, ignore_errors=True)
print("\nALL SCOPE TESTS PASSED")
