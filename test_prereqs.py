#!/usr/bin/env python3
"""Prerequisite-detection tests for mouse_scroll.py (mocked; nothing installed,
nothing actually run -- the subprocess call used for `apt` is stubbed).

Scenarios:
  A  everything present            -> no prompt, no apt, returns True
  B  tkinter missing, EOF stdin    -> declines the prompt, apt never called
  C  -y / assume_yes               -> calls the apt command, reloads tkinter
  C2 tkinter + xinput missing      -> both packages requested in one apt call
  D  apt fails (rc != 0)           -> manual fallback message, returns False
  G  no apt on the system          -> manual package-manager message, False
  H  Windows, tkinter missing      -> python.org message, no apt
  E  --check reports MISSING line
  F  --check reports OK line
"""
import builtins
import contextlib
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if "ms" in sys.modules:
    ms = sys.modules["ms"]
else:
    spec = importlib.util.spec_from_file_location(
        "ms", os.path.join(HERE, "mouse_scroll.py"))
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    sys.modules["ms"] = ms

class Run:
    def __init__(self):
        self.calls = []
        self.rc = 0

    def call(self, argv):
        self.calls.append(argv)
        return self.rc

run = Run()

def restore(ms):
    for a, v in getattr(ms, "_orig", {}).items():
        if a == "subprocess.call":
            subprocess_call = ms.subprocess.call if hasattr(ms, "subprocess") else None
            if ms._real_subprocess_call is not None:
                object.__setattr__(ms.subprocess, "call", ms._real_subprocess_call)
        else:
            setattr(ms, a, v)
    ms._orig = {}

_orig_input = builtins.input
_orig_subprocess_call = None

def stub(ms, **kw):
    global _orig_subprocess_call
    ms._orig = {a: getattr(ms, a) for a in kw if a != "subprocess.call"}
    if "subprocess.call" in kw:
        if _orig_subprocess_call is None:
            _orig_subprocess_call = __import__("subprocess").call
        ms._orig["subprocess.call"] = _orig_subprocess_call
        ms.subprocess.call = kw["subprocess.call"]
    for a, v in kw.items():
        if a != "subprocess.call":
            setattr(ms, a, v)
    ms._real_subprocess_call = _orig_subprocess_call

def run_check_output(ms):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ms.run_check()
    return rc, buf.getvalue()

def scenario(name, body):
    restore(ms)
    builtins.input = _orig_input
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            body()
        except AssertionError as e:
            print("FAIL %s -- %r" % (name, e)); sys.exit(1)
        except SystemExit as e:
            print("FAIL %s -- unexpected exit %r" % (name, e)); sys.exit(1)
    print("ok  ", name)

# A: everything present -> no prompt, no apt
def a():
    stub(ms, tk=object(), labwc_active=lambda: True,
         cmd_exists=lambda c: True)
    assert ms.ensure_prerequisites(False) is True
    assert run.calls == []
scenario("A ok (all present -> no prompt, no output)", a)

# B: tkinter missing, non-interactive stdin declines the prompt
def b():
    stub(ms, tk=None, labwc_active=lambda: True,
         cmd_exists=lambda c: c in ("apt-get", "sudo"),
         _reload_tkinter=lambda: (_ for _ in ()).throw(AssertionError("not called")),
         **{"subprocess.call": run.call})
    run.rc = 0; run.calls = []
    builtins.input = lambda p="": (_ for _ in ()).throw(EOFError)
    try:
        assert ms.ensure_prerequisites(False) is False
    finally:
        builtins.input = _orig_input
    assert run.calls == []
scenario("B ok (tkinter missing + non-interactive -> declines, apt not called)", b)

# C: assume_yes -> apt runs, tkinter reloads successfully
def c():
    reloaded = {"v": False}
    def reload_tk():
        reloaded["v"] = True
        ms.tk = object()
        return True
    stub(ms, tk=None, labwc_active=lambda: True,
         cmd_exists=lambda c: c in ("apt-get", "sudo"),
         _reload_tkinter=reload_tk,
         **{"subprocess.call": run.call})
    run.rc = 0; run.calls = []
    assert ms.ensure_prerequisites(True) is True
    assert run.calls == [["sudo", "apt-get", "install", "-y", "python3-tk"]], run.calls
    assert reloaded["v"]
scenario("C ok (-y -> apt python3-tk, tkinter reloaded)", c)

# C2: + xinput missing (no labwc, no gsettings) -> both packages in one call
def c2():
    state = {"xinput": False, "tk": False}
    def cmd(c):
        return c in ("apt-get", "sudo") or (c == "xinput" and state["xinput"])
    def reload_tk():
        state["tk"] = True
        state["xinput"] = True   # package lands: xinput now present
        ms.tk = object()
        return True
    stub(ms, tk=None, labwc_active=lambda: False,
         cmd_exists=cmd,
         _reload_tkinter=reload_tk,
         **{"subprocess.call": run.call})
    run.rc = 0; run.calls = []
    ms.subprocess.call = run.call  # ensure the stub is the one being called
    assert ms.ensure_prerequisites(True) is True
    assert len(run.calls) == 1
    assert run.calls[0][:4] == ["sudo", "apt-get", "install", "-y"]
    assert "python3-tk" in run.calls[0] and "x11-xserver-utils" in run.calls[0]
scenario("C2 ok (both packages requested in one apt call)", c2)

# D: apt fails (rc != 0) -> manual fallback, False
def d():
    stub(ms, tk=None, labwc_active=lambda: True,
         cmd_exists=lambda c: c in ("apt-get", "sudo"),
         _reload_tkinter=lambda: (_ for _ in ()).throw(AssertionError("not called")),
         **{"subprocess.call": run.call})
    run.rc = 1; run.calls = []
    assert ms.ensure_prerequisites(True) is False
    assert run.calls and run.calls[0][0] == "sudo"
scenario("D ok (apt failure -> manual fallback)", d)

# G: no apt on the system -> package-manager message, no call
def g():
    stub(ms, tk=None, labwc_active=lambda: True,
         cmd_exists=lambda c: False,
         _reload_tkinter=lambda: (_ for _ in ()).throw(AssertionError("not called")),
         **{"subprocess.call": run.call})
    run.rc = 0; run.calls = []
    assert ms.ensure_prerequisites(True) is False
    assert run.calls == []
scenario("G ok (no apt -> package-manager message, no apt call)", g)

# H: Windows without tkinter -> python.org advice, no apt
def h():
    stub(ms, tk=None, is_windows=lambda: True, is_linux=lambda: False,
         cmd_exists=lambda c: False,
         _reload_tkinter=lambda: (_ for _ in ()).throw(AssertionError("not called")),
         **{"subprocess.call": run.call})
    run.rc = 0; run.calls = []
    assert ms.ensure_prerequisites(True) is False
    assert run.calls == []
scenario("H ok (Windows -> python.org message, no apt)", h)

# E: --check reports MISSING
def e():
    stub(ms, tk=None, is_linux=lambda: True, labwc_active=lambda: False,
         cmd_exists=lambda c: False)
    rc, out = run_check_output(ms)
    assert rc == 0, rc
    assert "Prerequisites:" in out and "python3-tk" in out, out
scenario("E ok (--check shows MISSING line)", e)

# F: --check reports OK
def f():
    stub(ms, tk=object(), is_linux=lambda: True, labwc_active=lambda: True,
         cmd_exists=lambda c: True)
    rc, out = run_check_output(ms)
    assert rc == 0, rc
    assert "Prerequisites: OK" in out, out
scenario("F ok (--check shows OK line)", f)

restore(ms)
assert ms.subprocess.call is _orig_subprocess_call, "subprocess.call not restored"
builtins.input = _orig_input
print("\nall prerequisite checks passed")
