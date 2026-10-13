#!/usr/bin/env python3
"""Render the ZMK keymap as Markdown tables inside README.md.

The generated section sits between these markers in the README:

    <!-- keymap:start -->
    <!-- keymap:end -->

Usage:
    python3 scripts/keymap_to_readme.py          # rewrite README.md
    python3 scripts/keymap_to_readme.py --check  # exit 1 if README.md is out of date
"""

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYMAP = ROOT / "boards/shields/ergodash_ble/ergodash_ble.keymap"
README = ROOT / "README.md"

START = "<!-- keymap:start -->"
END = "<!-- keymap:end -->"

# Physical layout: 5 rows of 14 bindings, 7 per half.
ROWS, COLS = 5, 14
HALF = COLS // 2

KEY_LABELS = {
    "ESC": "Esc", "ESCAPE": "Esc", "TAB": "Tab", "CAPSLOCK": "Caps", "CAPS": "Caps",
    "SPACE": "Space", "RET": "Enter", "RETURN": "Enter", "ENTER": "Enter",
    "BSPC": "Bksp", "BACKSPACE": "Bksp", "DEL": "Del", "DELETE": "Del", "INS": "Ins", "INSERT": "Ins",
    "HOME": "Home", "END": "End", "PG_UP": "PgUp", "PG_DN": "PgDn",
    "LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓",
    "LSHFT": "Shift", "RSHFT": "Shift", "LSHIFT": "Shift", "RSHIFT": "Shift",
    "LCTRL": "Ctrl", "RCTRL": "Ctrl", "LALT": "Alt", "RALT": "AltGr",
    "LMETA": "Win", "RMETA": "Win", "LGUI": "Win", "RGUI": "Win", "LCMD": "Win", "RCMD": "Win",
    "LWIN": "Win", "RWIN": "Win",
    "GRAVE": "`", "MINUS": "-", "EQUAL": "=", "LBKT": "[", "RBKT": "]", "BSLH": "\\",
    "SEMI": ";", "SQT": "'", "COMMA": ",", "DOT": ".", "SLASH": "/",
    "PSCRN": "PrtSc", "PRINTSCREEN": "PrtSc", "SLCK": "ScrLk", "PAUSE_BREAK": "Pause",
    "C_VOL_UP": "Vol+", "C_VOL_DN": "Vol−", "C_MUTE": "Mute",
    "C_PP": "Play", "C_NEXT": "Next", "C_PREV": "Prev",
}

MOD_WRAPPERS = {
    "LS": "Shift+", "RS": "Shift+", "LC": "Ctrl+", "RC": "Ctrl+",
    "LA": "Alt+", "RA": "AltGr+", "LG": "Win+", "RG": "Win+",
}

RGB_LABELS = {
    "RGB_TOG": "RGB on/off", "RGB_ON": "RGB on", "RGB_OFF": "RGB off",
    "RGB_HUI": "Hue+", "RGB_HUD": "Hue−", "RGB_SAI": "Sat+", "RGB_SAD": "Sat−",
    "RGB_BRI": "Bright+", "RGB_BRD": "Bright−", "RGB_SPI": "Speed+", "RGB_SPD": "Speed−",
    "RGB_EFF": "Effect+", "RGB_EFR": "Effect−",
}

BT_LABELS = {
    "BT_CLR": "BT clear", "BT_CLR_ALL": "BT clear all",
    "BT_NXT": "BT next", "BT_PRV": "BT prev", "BT_DISC": "BT disc",
}

EXT_POWER_LABELS = {"EP_TOG": "Power toggle", "EP_ON": "Power on", "EP_OFF": "Power off"}

SIMPLE_BEHAVIORS = {
    "&trans": "▽", "&none": "", "&bootloader": "Boot", "&sys_reset": "Reset",
    "&reset": "Reset", "&caps_word": "CapsWord", "&key_repeat": "Repeat",
}


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def key_label(code):
    m = re.fullmatch(r"(\w+)\((.+)\)", code)
    if m and m.group(1) in MOD_WRAPPERS:
        return MOD_WRAPPERS[m.group(1)] + key_label(m.group(2))
    if code in KEY_LABELS:
        return KEY_LABELS[code]
    if re.fullmatch(r"N\d", code) or re.fullmatch(r"NUMBER_\d", code):
        return code[-1]
    return code


def binding_label(binding, layer_names):
    parts = binding.split()
    behavior, params = parts[0], parts[1:]

    if behavior in SIMPLE_BEHAVIORS and not params:
        return SIMPLE_BEHAVIORS[behavior]
    if behavior == "&kp" and len(params) == 1:
        return key_label(params[0])
    if behavior in ("&mo", "&to", "&tog", "&sl") and len(params) == 1:
        name = layer_names.get(params[0], params[0])
        prefix = {"&mo": "", "&to": "To ", "&tog": "Toggle ", "&sl": "Once "}[behavior]
        return f"{prefix}{name}"
    if behavior == "&lt" and len(params) == 2:
        return f"{key_label(params[1])} / {layer_names.get(params[0], params[0])}"
    if behavior == "&mt" and len(params) == 2:
        return f"{key_label(params[1])} / {key_label(params[0])}"
    if behavior == "&bt":
        if params[:1] == ["BT_SEL"] and len(params) == 2:
            return f"BT {params[1]}"
        if params[:1] == ["BT_DISC"] and len(params) == 2:
            return f"BT disc {params[1]}"
        if len(params) == 1:
            return BT_LABELS.get(params[0], params[0])
    if behavior == "&rgb_ug" and len(params) == 1:
        return RGB_LABELS.get(params[0], params[0])
    if behavior == "&ext_power" and len(params) == 1:
        return EXT_POWER_LABELS.get(params[0], params[0])
    if behavior == "&out" and len(params) == 1:
        return {"OUT_USB": "USB", "OUT_BLE": "BLE", "OUT_TOG": "USB/BLE"}.get(params[0], params[0])

    # Unknown behavior: show it as written.
    return binding


def parse_keymap(text):
    defines = dict(re.findall(r"^\s*#define\s+(\w+)\s+(\d+)\s*$", text, flags=re.M))
    body = strip_comments(text)

    keymap = re.search(r"compatible\s*=\s*\"zmk,keymap\"\s*;(.*)", body, flags=re.S)
    if not keymap:
        sys.exit(f"error: no zmk,keymap node found in {KEYMAP}")

    layers = []
    for m in re.finditer(r"(\w+)\s*\{([^{}]*?bindings\s*=\s*<(.*?)>\s*;[^{}]*)\}", keymap.group(1), flags=re.S):
        node, props, bindings = m.groups()
        display = re.search(r"display-name\s*=\s*\"([^\"]*)\"", props)
        name = display.group(1) if display else node.removesuffix("_layer").replace("_", " ").title()
        tokens = ["&" + b.strip() for b in bindings.split("&") if b.strip()]
        layers.append((name, tokens))

    # Map layer references (#define LOWER 1, or plain indices) to layer names.
    layer_names = {str(i): name for i, (name, _) in enumerate(layers)}
    for macro, index in defines.items():
        if index in layer_names:
            layer_names[macro] = layer_names[index]
    return layers, layer_names


def cell(label):
    return f"<td align=\"center\">{html.escape(label, quote=False)}</td>"


def render(layers, layer_names):
    # HTML tables instead of Markdown ones: Markdown tables always need a header row,
    # which would render as an empty first row here.
    out = [
        f"<!-- Generated by scripts/keymap_to_readme.py from {KEYMAP.relative_to(ROOT)}; do not edit by hand. -->",
        "",
        "▽ = falls through to the layer below, blank = no key.",
    ]
    separator = '<td align="center">‖</td>'

    for name, bindings in layers:
        if len(bindings) != ROWS * COLS:
            sys.exit(f"error: layer '{name}' has {len(bindings)} bindings, expected {ROWS * COLS}")
        cells = [cell(binding_label(b, layer_names)) for b in bindings]
        out += ["", f"#### {name}", "", "<table>"]
        for r in range(ROWS):
            row = cells[r * COLS:(r + 1) * COLS]
            out.append("<tr>" + "".join(row[:HALF] + [separator] + row[HALF:]) + "</tr>")
        out.append("</table>")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if README.md is out of date instead of writing it")
    args = parser.parse_args()

    layers, layer_names = parse_keymap(KEYMAP.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")
    if START not in readme or END not in readme:
        sys.exit(f"error: README.md must contain {START} and {END}")

    before, rest = readme.split(START, 1)
    _, after = rest.split(END, 1)
    updated = f"{before}{START}\n{render(layers, layer_names)}\n{END}{after}"

    if args.check:
        if updated != readme:
            sys.exit("README.md keymap section is out of date; run: python3 scripts/keymap_to_readme.py")
        print("README.md keymap section is up to date")
    elif updated != readme:
        README.write_text(updated, encoding="utf-8")
        print("Updated README.md")
    else:
        print("README.md already up to date")


if __name__ == "__main__":
    main()
