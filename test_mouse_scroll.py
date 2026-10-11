#!/usr/bin/env python3
"""Tests for the labwc rc.xml writer in mouse_scroll.py.

Run from the project directory:
    python3 test_mouse_scroll.py

They exercise set_labwc() against the real shapes found in the wild (missing
file, the default Raspberry Pi self-closing ``<openbox_config/>`` skeleton,
openbox/labwc roots, an existing ``<libinput>`` block, an existing
``<naturalScroll>``, toggling off, and a document that is *not* well-formed)
and assert that each result is valid XML with exactly one declaration and the
correct ``<naturalScroll>`` value.

These guard the tricky XML manipulation — they would have flagged the
"two ``<?xml ...?>`` declarations" regression in seconds.
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET

# Point HOME at a scratch dir BEFORE importing mouse_scroll, so LABWC_HOME_RC
# (computed from `~` at import time) lives in a throwaway location.
_TMPHOME = tempfile.mkdtemp(prefix="mouse_scroll_test_")
os.environ["HOME"] = _TMPHOME
os.environ["LABWC_PID"] = "1"

import mouse_scroll as ms  # noqa: E402

RC = os.path.join(_TMPHOME, ".config", "labwc", "rc.xml")
RC_DIR = os.path.dirname(RC)


SCENARIOS = [
    ("no file -> create clean config", True, None),
    ("raspberry-pi skeleton (self-closing <openbox_config/>)", True,
     '<?xml version="1.0"?>\n<openbox_config xmlns="http://openbox.org/3.4/rc"/>\n'),
    ("openbox root with existing children", True,
     '<?xml version="1.0"?>\n<openbox_config>\n  <keyboard><keybind key="A-F4"><action name="Quit"/></keybind></keyboard>\n</openbox_config>\n'),
    ("labwc root, no existing <libinput>", True,
     '<?xml version="1.0"?>\n<labwc_config>\n  <mouse><default/></mouse>\n</labwc_config>\n'),
    ("labwc root, existing <libinput> (preserved)", True,
     '<?xml version="1.0"?>\n<labwc_config>\n  <libinput><device category="default"><pointerSpeed>0.3</pointerSpeed></device></libinput>\n</labwc_config>\n'),
    ("toggle: already enabled -> enable again", True,
     '<?xml version="1.0"?>\n<labwc_config><libinput><device category="default"><naturalScroll>yes</naturalScroll></device></libinput></labwc_config>\n'),
    ("toggle: enabled -> disable", False,
     '<?xml version="1.0"?>\n<labwc_config><libinput><device category="default"><naturalScroll>yes</naturalScroll></device></libinput></labwc_config>\n'),
    ("fresh disable (no <naturalScroll> yet)", False,
     '<?xml version="1.0"?>\n<labwc_config>\n  <mouse><default/></mouse>\n</labwc_config>\n'),
    ("BROKEN file (dup <?xml?> from old bug) -> clean rebuild", True,
     '<?xml version="1.0"?>\n<labwc_config>\n<?xml version="1.0"?>\n<openbox_config xmlns="http://openbox.org/3.4/rc"/>\n  <libinput>\n    <device category="non-touch"><naturalScroll>yes</naturalScroll></device>\n    <device category="touch"><naturalScroll>yes</naturalScroll></device>\n  </libinput>\n</labwc_config>\n'),
]


def check(name, enable, seed):
    if os.path.exists(RC):
        os.remove(RC)
    if seed is not None:
        os.makedirs(RC_DIR, exist_ok=True)
        with open(RC, "w", encoding="utf-8") as f:
            f.write(seed)

    ok = ms.set_labwc(enable)
    content = open(RC, encoding="utf-8").read() if os.path.exists(RC) else ""

    problems = []
    if not ok:
        problems.append("set_labwc returned False")
    if not content:
        problems.append("no rc.xml produced")
    else:
        if not content.startswith("<?xml"):
            problems.append("first line is not an XML declaration")
        n = content.count("<?xml")
        if n != 1:
            problems.append("expected exactly one <?xml ...?> declaration, got %d" % n)
        want = "yes" if enable else "no"
        try:
            root = ET.fromstring(content)
        except Exception as e:
            problems.append("XML parse failed: %s" % e)
            root = None
        if root is not None:
            els = [el for el in root.iter() if el.tag.endswith("naturalScroll")]
            if len(els) != 1:
                problems.append("expected exactly one <naturalScroll>, got %d" % len(els))
            elif els[0].text is None or els[0].text.strip().lower() != want:
                problems.append("<naturalScroll> is %r, want %r" % (els[0].text, want))
    return problems


def main():
    fails = 0
    for name, enable, seed in SCENARIOS:
        problems = check(name, enable, seed)
        if problems:
            fails += 1
            print("FAIL  %s" % name)
            for p in problems:
                print("        - %s" % p)
        else:
            print("PASS  %s" % name)
    print()
    if fails:
        print("%d of %d scenarios FAILED" % (fails, len(SCENARIOS)))
        return 1
    print("All %d scenarios passed." % len(SCENARIOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
