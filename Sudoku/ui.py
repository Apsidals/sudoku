"""
Reading the widget tree, for the screens that are not the board.

The board is read from pixels because it is drawn, not laid out - there
are no views to ask about which digit is in which cell. Everything
around it is ordinary Android views, and those can simply be asked:
`uiautomator dump` gives every visible node with its text, its id and
its bounds, so a button can be found by what it says rather than by
where it was the last time somebody looked.

That matters most for the screens nobody planned for. The happy path -
result, difficulty sheet, board - is worth driving from fixed
coordinates because it is fast and it is the same every time. Rating
prompts, promos, consent forms and interstitials are not the same every
time, and a dump plus "tap the thing that says Close" handles a screen
this code has never seen.

It costs about three seconds a call, which is why it is the fallback
and not the road.
"""

import re
import subprocess
import xml.etree.ElementTree as ElementTree

import config

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Things that dismiss a screen without agreeing to anything. Ordered:
# the earlier a label appears, the more it is preferred, so a dialog
# offering both "No thanks" and "Continue" takes the one that does not
# opt in to whatever is being offered.
DISMISS_LABELS = [
    "no thanks", "not now", "later", "maybe later", "no, thanks",
    "skip", "dismiss", "cancel", "close", "not interested",
    "×", "x", "✕", "✖",
    "continue", "ok", "got it", "done",
]

# The same idea, for the buttons that carry no text at all. Matched
# against the resource id, and deliberately narrow: "cancel" and
# "close" are unambiguous, whereas "no" or "back" would match half the
# ids in a layout.
DISMISS_IDS = [
    "cancelbtn", "closebtn", "btnclose", "btncancel", "ivclose",
    "imgclose", "iv_close", "btn_close", "btn_cancel", "skipbtn",
    "btn_skip", "close", "cancel", "dismiss", "skip",
]


def _adb(args, timeout=25):
    cmd = [config.ADB_PATH]
    if config.DEVICE_SERIAL:
        cmd += ["-s", config.DEVICE_SERIAL]
    return subprocess.run(
        cmd + args, capture_output=True, text=True, timeout=timeout,
    )


def dump():
    """
    Every visible node, as dicts of text, desc, id, clickable and centre.

    Returns [] rather than raising when the dump fails, which it does
    when the foreground is a surface uiautomator cannot walk - some
    video ads are exactly that - because "nothing to see" is a useful
    answer there and an exception is not.
    """
    result = _adb([
        "shell",
        "uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 && cat /sdcard/ui.xml",
    ])
    text = result.stdout.strip()
    if not text.startswith("<?xml"):
        return []
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []

    nodes = []
    for node in root.iter("node"):
        match = _BOUNDS.match(node.get("bounds", ""))
        if not match:
            continue
        left, top, right, bottom = (int(v) for v in match.groups())
        if right <= left or bottom <= top:
            continue
        nodes.append({
            "text": (node.get("text") or "").strip(),
            "desc": (node.get("content-desc") or "").strip(),
            "id": (node.get("resource-id") or "").split("/")[-1],
            "class": node.get("class") or "",
            "package": node.get("package") or "",
            "clickable": node.get("clickable") == "true",
            "centre": ((left + right) // 2, (top + bottom) // 2),
            "bounds": (left, top, right, bottom),
            "area": (right - left) * (bottom - top),
        })
    return nodes


def _label(node):
    return (node["text"] or node["desc"]).strip().lower()


def _contains(node, point):
    left, top, right, bottom = node["bounds"]
    return left <= point[0] <= right and top <= point[1] <= bottom


def find(nodes, wanted, exact=False):
    """
    Where to tap for the thing labelled `wanted`.

    Not simply the label's own centre. In this app the text and the
    thing you press are different views: the "Beginner" row on the New
    Game sheet is a non-clickable TextView at x=407 sitting inside a
    clickable row at x=540, and the label is not centred in its row. A
    tap on the label happens to work here because the touch falls
    through, but that is luck, and it does not hold for the sheet's
    two-up bottom row where "Fast" and "16x16" are separate buttons
    side by side.

    So: find the label, then hand back the middle of the smallest
    clickable view that contains it, falling back to the label itself
    when nothing clickable does.
    """
    wanted = wanted.lower()
    for node in nodes:
        label = _label(node)
        if label != wanted and (exact or wanted not in label):
            continue
        if node["clickable"]:
            return node["centre"]
        holders = [
            other for other in nodes
            if other["clickable"] and _contains(other, node["centre"])
        ]
        if holders:
            return min(holders, key=lambda n: n["area"])["centre"]
        return node["centre"]
    return None


def find_dismiss(nodes, corners=True):
    """
    Where to tap to get out of a screen, or None.

    Three passes, most trustworthy first.

    Text, when there is any. Then the resource id, which is the pass
    that earns its keep: the rating prompt this app shows after a win
    has its close button as a bare X drawn into an ImageView, with no
    text and no content-desc, sitting in the middle of the screen
    rather than a corner - invisible to the other two passes. It is
    called "cancelBtn", and ids like that are near-universal.

    Then, only if neither found anything, a small clickable thing in a
    top corner, which is what an unlabelled interstitial close button
    usually is.

    The full-screen dim behind a dialog is clickable too and often
    dismisses it, but it is excluded everywhere here: on the screens
    where it does not dismiss, it is a tap straight into whatever the
    dialog is advertising.
    """
    small = [
        node for node in nodes
        if node["clickable"] and node["area"] < config.MAX_DISMISS_AREA
    ]

    for wanted in DISMISS_LABELS:
        for node in small:
            label = _label(node)
            if label == wanted or (len(wanted) > 3 and wanted in label):
                return node["centre"], label

    for wanted in DISMISS_IDS:
        for node in small:
            name = node["id"].lower()
            if wanted in name:
                return node["centre"], "#%s" % node["id"]

    # Only for screens that are not the game's own. Every screen in
    # this app has small unlabelled buttons in its top corners - the
    # back arrow, the settings gear, the theme picker - and "tap the
    # small thing in the corner" walks straight into them: on the home
    # screen it opened the shop, and on a board it left the puzzle. An
    # interstitial's close button is worth guessing at. The game's own
    # chrome is not.
    if not corners:
        return None

    corner_y = config.SCREEN_H * 0.22
    candidates = [
        node for node in small
        if node["area"] < 140 * 140
        and node["bounds"][1] < corner_y
        and (node["bounds"][0] < 220 or node["bounds"][2] > config.SCREEN_W - 220)
    ]
    if candidates:
        best = min(candidates, key=lambda n: n["area"])
        return best["centre"], "(unlabelled corner button)"
    return None


def describe(nodes, limit=12):
    """A short summary of a screen, for the log when something is odd."""
    labels = []
    for node in nodes:
        label = _label(node)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return ", ".join(labels) if labels else "(no readable text)"
