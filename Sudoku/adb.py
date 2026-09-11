"""
Thin wrapper around ADB for screen capture and touch input.

Requires the BlueStacks adb at config.ADB_PATH and the emulator's adb
port reachable (`HD-Adb.exe connect 127.0.0.1:5575`).
"""

import subprocess
import time

import cv2
import numpy as np

import config


def _base_cmd():
    cmd = [config.ADB_PATH]
    if config.DEVICE_SERIAL:
        cmd += ["-s", config.DEVICE_SERIAL]
    return cmd


def connect() -> None:
    """Attach to the emulator. Harmless if already attached."""
    subprocess.run(
        [config.ADB_PATH, "connect", config.DEVICE_SERIAL],
        capture_output=True,
    )


def screenshot(tries: int = 4) -> np.ndarray:
    """
    Capture the current screen as a BGR array.

    Retried, and reconnected to between attempts, because the capture
    does not only fail when something is wrong: the emulator drops the
    connection when it restarts, and comes back a few seconds later on
    the same port. A run meant to last hours should not end because one
    frame arrived empty - which is what an outage looks like here, an
    empty buffer rather than an error, so it surfaced as an assertion
    failure inside cv2.imdecode.
    """
    cmd = _base_cmd() + ["exec-out", "screencap", "-p"]
    for attempt in range(tries):
        raw = subprocess.run(cmd, capture_output=True).stdout
        if raw:
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is not None:
                return img
        if attempt + 1 < tries:
            time.sleep(1.5)
            connect()
    raise RuntimeError(
        "Failed to capture the screen %d times. Check the connection with "
        "`\"%s\" connect %s`." % (tries, config.ADB_PATH, config.DEVICE_SERIAL)
    )


def reconnect() -> None:
    """
    Drop the connection and take it again.

    `connect` alone does not clear a device that has gone *offline* -
    adb keeps handing back the dead entry, and every command fails on
    it. Dropping it first is what lets the next connect find a live
    one, once there is a live one to find.
    """
    subprocess.run([config.ADB_PATH, "disconnect", config.DEVICE_SERIAL],
                   capture_output=True)
    connect()


def _run_adb(args, tries: int = 4):
    """
    Run an adb command, reconnecting and retrying if the device drops.

    Two different failures land here and both are worth surviving. The
    adb server dies from time to time - the run that reached 133 wins
    ended that way, mid-board, on `device not found`. And the emulator
    itself goes *offline*, which needs the connection dropped before it
    can be retaken.

    Retrying is safe for both because neither failure reaches the
    device: nothing was tapped, so nothing is tapped twice by trying
    again. The backoff lengthens, because an emulator coming back up
    takes seconds rather than milliseconds.
    """
    result = None
    for attempt in range(tries):
        result = subprocess.run(_base_cmd() + args, capture_output=True,
                                text=True)
        if result.returncode == 0:
            return result
        if attempt + 1 < tries:
            time.sleep(1.5 * (attempt + 1))
            reconnect()
    raise RuntimeError(
        "adb failed %d times: %s"
        % (tries, (result.stderr or "").strip() if result else "no result")
    )


def wait_for_device(timeout_s: int = 600) -> bool:
    """
    Block until the emulator answers again, or give up.

    For the case the retries above cannot cover: the emulator is not
    slow, it is gone - closed, restarting, or wedged. There is nothing
    to tap until it is back, and a run that has hours left in it should
    wait for it rather than end.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        reconnect()
        probe = subprocess.run(_base_cmd() + ["shell", "echo", "ALIVE"],
                               capture_output=True, text=True)
        if probe.returncode == 0 and "ALIVE" in (probe.stdout or ""):
            return True
        time.sleep(5)
    return False


def tap(x: int, y: int) -> None:
    _run_adb(["shell", "input", "tap", str(int(x)), str(int(y))])


def tap_sequence(points, gap_ms: int = 0, batch: int = 20) -> None:
    """
    Tap a sequence of points, several per adb call.

    Each `input tap` costs the device about 100ms whatever else happens,
    and a separate adb round trip adds ~25ms on top; chaining them in
    one shell command removes that round trip. Worth having when a
    solved board is 50 cells and every cell is two taps.
    """
    points = list(points)
    for start in range(0, len(points), batch):
        parts = []
        for index, (x, y) in enumerate(points[start:start + batch]):
            if index and gap_ms > 0:
                parts.append(f"sleep {gap_ms / 1000.0:.3f}")
            parts.append(f"input tap {int(x)} {int(y)}")
        _run_adb(["shell", " ; ".join(parts)])


def key(code: int) -> None:
    """Press a hardware key. 4 is BACK."""
    try:
        _run_adb(["shell", "input", "keyevent", str(code)])
    except RuntimeError:
        pass  # a key that did not go in is not worth ending a run over


def foreground_package() -> str:
    """The package that currently owns the focused window, or ""."""
    cmd = _base_cmd() + ["shell", "dumpsys window"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "mCurrentFocus" in line and "/" in line:
            token = line.split()[-1]
            return token.split("/")[0].lstrip("{")
    return ""


def is_game_foreground() -> bool:
    return foreground_package() == config.GAME_PACKAGE


def sleep_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)
