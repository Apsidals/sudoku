"""
Play Beginner boards, one after another, for as long as it is left
running.

The loop is four steps and nothing else:

    wait for a board  ->  solve it  ->  wait for the win  ->
    tap New Game, tap Beginner

Both of those taps are at fixed coordinates. They were found once in
the widget tree and written down in config, and they do not move: the
result screen's New Game button and the sheet's Beginner row are in the
same place every time.

Everything else on screen is treated the same way, and it is
deliberately not clever about it. An earlier version tried to work out
what each unexpected screen was and do the right thing on it, and what
that bought was a run that wandered into the Daily Challenge, tapped
"continue" on a board with two mistakes already on it, and spent a
minute pressing back at a screen it had misidentified. So: anything
that is not a board and not the win screen gets `recover()` - one look
for a close button, then the back key, then a relaunch of the game's
own activity - and then the loop asks for a board again. A relaunch
always lands somewhere the two taps work from, which is what makes this
safe to leave running.
"""

import argparse
import sys
import time

import cv2

import adb
import config
import game
import solver
import ui
import vision


def on_board(img):
    """Is a playable board on screen?"""
    try:
        vision.find_grid(img)
        return True
    except vision.BoardReadError:
        return False


def won(img):
    """
    Is the end-of-board screen up?

    Both of its forms - the result card, and the New Game sheet drawn
    over it - sit on a blue field, and no other screen in this app
    does: the board, the menus and the settings are all near-white.
    """
    sample = img[::16, ::16].astype(int)
    return float(((sample[:, :, 0] - sample[:, :, 2]) > 25).mean()) > 0.25


# How many calls a screen may survive before it is relaunched out of
# rather than asked politely again. Three is two gentle attempts - a
# close button, then back - and then the one that works.
RELAUNCH_AFTER = 3

_stuck_at = None
_stuck_count = 0


def recover(verbose=True):
    """
    Get off whatever this screen is. One rung per call.

    A close button if the widget tree offers one, then the back key,
    then a relaunch. Nothing here tries to understand an ad, a rating
    prompt or a promo - it only ever looks for the way out, and the
    relaunch is the way out that always works.

    The rungs are climbed by repetition, not by one call: a screen that
    is still here after RELAUNCH_AFTER attempts has answered for the
    two gentle rungs, and gets the relaunch. Without that the ladder
    has a rung it can never leave. An interstitial runs inside the
    game's own package, so `ours` is true on it, so the back branch is
    taken - and taken again on the next call, and the next, because
    back does nothing to an ad that does not offer a way out. A run
    spent its whole length pressing back at one AppLovin playable and
    won nothing.
    """
    global _stuck_at, _stuck_count

    package, activity = current_activity()
    where = "%s/%s" % (package or "?", activity or "?")
    ours = package == config.GAME_PACKAGE

    if where == _stuck_at:
        _stuck_count += 1
    else:
        _stuck_at, _stuck_count = where, 1

    if _stuck_count >= RELAUNCH_AFTER:
        if verbose:
            print("  %s: still here after %d - relaunching"
                  % (where, _stuck_count))
        relaunch()
        adb.sleep_ms(2000)
        _stuck_at, _stuck_count = None, 0
        return

    # On the game's own screens, only take a way out that is labelled
    # or named as one. Guessing at unlabelled corner buttons there
    # finds the back arrow and the settings gear, which is how an
    # earlier run kept leaving boards it was about to solve.
    way_out = ui.find_dismiss(ui.dump(), corners=not ours)
    if way_out:
        (x, y), label = way_out
        if verbose:
            print("  %s: closing %s" % (where, label))
        adb.tap(x, y)
        adb.sleep_ms(1200)
        return

    if ours and activity != config.HOME_ACTIVITY:
        # Back is safe inside the game, except on the home screen where
        # it raises a "quit?" dialog that the run then has to cancel.
        if verbose:
            print("  %s: back" % where)
        adb.key(4)
        adb.sleep_ms(1200)
        return

    if verbose:
        print("  %s: relaunching" % where)
    relaunch()
    adb.sleep_ms(2000)


def relaunch():
    """
    Kill the game and start it again.

    This is the rung that has to work, because it is the one that gets
    out of an interstitial offering no close button - and those exist.
    An AppLovin playable held a run for its whole length: its widget
    tree was three labels, none of them a way out, and back did
    nothing to it.

    Starting the app is not enough to escape one. Both `am start` and
    the launcher intent resolve to the task the ad is already sitting
    on top of, so they bring the ad itself back to the front. Only
    force-stop actually takes it off the screen, and the board survives
    it: the game writes its puzzle down and offers it back as Continue.

    Then start it again, by whichever way this device allows. `am start
    -n` names the activity and is the precise way in, but it only works
    where that activity is exported - BlueStacks refuses it with a
    Permission Denial, and prints the refusal rather than returning it,
    so it has to be read out of the output. The launcher intent needs
    no such permission and lands where tapping the icon would.
    """
    ui._adb(["shell", "am force-stop %s" % config.GAME_PACKAGE])
    adb.sleep_ms(600)

    result = ui._adb(["shell", "am start -n %s/%s"
                      % (config.GAME_PACKAGE, config.GAME_ACTIVITY)])
    output = (result.stdout or "") + (result.stderr or "")
    if "Exception" in output or "Error" in output:
        ui._adb(["shell", "monkey -p %s -c android.intent.category.LAUNCHER 1"
                 % config.GAME_PACKAGE])


def current_activity():
    """The focused package and activity short name."""
    out = ui._adb(["shell", "dumpsys window"]).stdout
    for line in out.splitlines():
        if "mCurrentFocus" in line and "/" in line:
            token = line.split()[-1].rstrip("}")
            package, _, activity = token.partition("/")
            return package.lstrip("{"), activity.rsplit(".", 1)[-1]
    return "", ""


def _band(img):
    """The strip that tells the result card apart from the open sheet."""
    patch = img[1450:1550, 300:800].astype(int)
    return float((patch[:, :, 0] - patch[:, :, 2]).mean())


def on_sheet(img):
    """
    Is the New Game sheet open?

    It and the result card behind it share the blue field, and they are
    told apart at about y=1500: on the result card that is open
    background, still tinted blue, and on the sheet it is inside the
    white panel.

    Worth telling apart, because the difficulty tap is only safe on the
    sheet. That same point on the result card is nothing, and a stray
    tap at the New Game position while the sheet is open lands on the
    "Fast" row, which quietly starts a 6x6 game instead.
    """
    return won(img) and _band(img) < 12


def start_next(verbose=True):
    """
    Tap New Game, then Beginner - checking in between.

    The check is one screenshot and it pays for itself. Posting both
    taps blind and letting the loop sort out the result costs a whole
    extra pass whenever the first tap has not landed yet, which was
    about a third of boards and ten seconds each time.
    """
    img = adb.screenshot()
    if on_sheet(img):
        return _pick_difficulty(verbose)

    if won(img):
        # The result card: the blue field the two fixed taps were
        # measured on, and the path nearly every board takes.
        adb.tap(*config.NEW_GAME_BUTTON)
        adb.sleep_ms(config.SHEET_WAIT_MS)
        if on_sheet(adb.screenshot()):
            return _pick_difficulty(verbose)
        return False  # not there yet; the loop will come round again

    # Not the blue field, so this is the home screen - which recovery
    # lands on - or the sheet already open over it. `on_sheet` cannot
    # tell those apart: it keys off the blue behind the sheet, and over
    # the home screen there is grey dim instead, so it says "no sheet"
    # to a sheet that is really there. Tapping New Game on that answer
    # is the one thing that must not happen here, because with the
    # sheet open that point is the "Fast" row and quietly starts a 6x6
    # game. So ask the widget tree instead of the pixels. It costs
    # about three seconds and only on this path.
    nodes = ui.dump()
    if _sheet_is_open(nodes):
        row = ui.find(nodes, config.DIFFICULTY)
        if row:
            if verbose:
                print("  new game -> %s (widget tree)" % config.DIFFICULTY)
            adb.tap(*row)
            adb.sleep_ms(config.BOARD_WAIT_MS)
            return True

    new_game = ui.find(nodes, "new game")
    if new_game:
        adb.tap(*new_game)
        adb.sleep_ms(config.SHEET_WAIT_MS)
    return False


def _sheet_is_open(nodes):
    """
    Is the New Game sheet in this widget tree?

    Asked before trusting a difficulty row found by name, because the
    board draws its own difficulty in the header: on a Beginner board
    "Beginner" is right there at the top of the screen, and tapping
    what `find` hands back for it would be a tap into the header rather
    than a new game. These two are only ever on the sheet, and the
    sheet always has both however far the player has unlocked.
    """
    labels = {(node["text"] or node["desc"]).strip().lower() for node in nodes}
    return "fast" in labels and "extreme" in labels


def _pick_difficulty(verbose=True):
    """Tap the difficulty row on a sheet already known to be open."""
    if verbose:
        print("  new game -> %s" % config.DIFFICULTY)
    adb.tap(*config.DIFFICULTY_ROW)
    adb.sleep_ms(config.BOARD_WAIT_MS)
    return True


def wait_for_board(verbose=True, timeout_s=90):
    """
    Block until a board is on screen. Returns the frame it was seen in.

    Whatever is in the way - an ad, the rating prompt, the home screen,
    a half-finished board's own menu - is handled the same way: take
    one step to get off it, then look again.
    """
    deadline = time.time() + timeout_s
    stray = 0
    loading = 0
    while time.time() < deadline:
        img = game.stable_screenshot(tries=3)
        if on_board(img):
            return img

        package, activity = current_activity()

        # The board's own activity, with no lattice on it yet: it is
        # still drawing. Wait. Reaching for the back key here is how an
        # earlier version kept opening the pause menu over a board that
        # was about to appear.
        if package == config.GAME_PACKAGE and activity == config.BOARD_ACTIVITY:
            if loading < 5:
                loading += 1
                adb.sleep_ms(500)
                continue

        # The result card, the New Game sheet, and the home screen all
        # take the same two taps: New Game sits in the same place on
        # the home screen as it does on the result card, and the sheet
        # it opens is the same sheet. So none of these needs its own
        # handling, or a widget dump to work out which it is.
        if package == config.GAME_PACKAGE and (
            won(img) or activity in (config.RESULT_ACTIVITY,
                                     config.HOME_ACTIVITY,
                                     config.BOARD_ACTIVITY)
        ):
            start_next(verbose)
            stray = 0
            loading = 0
            continue

        recover(verbose)
        stray += 1
        loading = 0
        if stray % 4 == 0:
            # Off the beaten track for a while. Try the two taps anyway:
            # from most of the game's screens they still lead to a board.
            start_next(verbose)
        adb.sleep_ms(300)
    raise TimeoutError("no board on screen after %ds" % timeout_s)


def wait_for_win(verbose=True, timeout_s=20):
    """
    Wait for the board just played to be accepted as finished.

    This is what counts a win, rather than "the moves were posted".
    They are not the same thing: a tap can miss. Returns False if the
    board is still up, and the loop then reads what is there now and
    plays the rest.

    Asked of the activity rather than the pixels wherever that can
    answer it. The two agree - the result card is the blue field - but
    they do not cost the same: a screenshot is 369ms of PNG on a
    throttled machine, and `dumpsys window` is 94ms. This runs while
    the board is still up and mostly answers "not yet", so the cheap
    question is the one worth asking, and the pixel test is kept for
    the screens where the activity alone is not conclusive.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        package, activity = current_activity()
        ours = package == config.GAME_PACKAGE

        if ours and activity == config.RESULT_ACTIVITY:
            return True

        # Still on the board: nothing a screenshot could add.
        if ours and activity == config.BOARD_ACTIVITY:
            adb.sleep_ms(250)
            continue

        # An ad, the sheet, anything else - fall back to the pixels.
        if won(adb.screenshot()):
            return True
        adb.sleep_ms(350)
    return False


def read_board(img, tries=3):
    """
    Read and solve, giving a board that is still drawing itself a
    second chance.

    A new board fades its givens in, and a frame caught partway through
    that is missing some of them. The missing ones are not misread -
    they are simply not there yet - so the read comes back clean and
    the solver is what notices, by finding two ways to complete a
    puzzle that has exactly one. Which is the check working: the answer
    is to look again, not to tap anything in.
    """
    last = None
    for attempt in range(tries):
        try:
            return game.read(img)
        except (vision.BoardReadError, solver.Unsolvable) as error:
            last = error
            if attempt + 1 < tries:
                adb.sleep_ms(700)
                img = game.stable_screenshot(tries=4)
    raise last


def leave_board(verbose=True):
    """
    Abandon the board on screen and go back to the home screen.

    For a board that will not read even after settling - which should
    not happen, and if it does, the run should get a different puzzle
    rather than sit on this one forever. The back arrow is the game's
    own, at the top left of every board.
    """
    if verbose:
        print("  leaving this board")
    try:
        adb.tap(*config.BOARD_BACK_ARROW)
    except RuntimeError:
        # This runs inside an error handler. A back arrow that could
        # not be tapped is not a reason to lose the run on top of the
        # board - the loop's own guard will wait for the device.
        return
    adb.sleep_ms(1400)


def _save_debug(name):
    """Write a debug frame, or shrug. Never raise from an error handler."""
    try:
        cv2.imwrite(config.debug_path(name), adb.screenshot())
    except (RuntimeError, cv2.error):
        pass


def run(limit=None, verbose=True):
    """Play boards until `limit` wins, or forever."""
    adb.connect()
    wins = 0
    started = time.time()

    while limit is None or wins < limit:
        board_started = time.time()
        try:
            try:
                img = wait_for_board(verbose)
                board = read_board(img)
            except (vision.BoardReadError, solver.Unsolvable) as error:
                # The screen is a board but not one this can trust, and
                # it has already been given time to settle. Do not tap a
                # guess into it: abandon it and take a fresh puzzle.
                print("  refused: %s" % error)
                _save_debug("debug_refused.png")
                leave_board(verbose)
                continue
            except TimeoutError as error:
                # Say relaunching and mean it. This used to call
                # recover(), which on an interstitial takes the back
                # rung and leaves the screen exactly as it found it.
                print("  %s - relaunching" % error)
                relaunch()
                adb.sleep_ms(2000)
                continue

            try:
                posted = game.play(board, verbose=verbose)
            except RuntimeError as error:
                print("  aborted: %s" % error)
                _save_debug("debug_aborted.png")
                leave_board(verbose)
                continue

            if not wait_for_win(verbose):
                print("  %d moves posted, board still up - finishing it"
                      % posted)
                continue

            wins += 1
            elapsed = time.time() - board_started
            rate = 3600.0 * wins / (time.time() - started)
            print("  won %d  (%d cells, %.1fs)  %.0f boards/hour"
                  % (wins, posted, elapsed, rate))

        except RuntimeError as error:
            # The last net, and the reason it is here: an adb failure
            # can be raised while another one is being handled, and
            # that pair ended a run at 65 wins. Anything adb-shaped
            # that got past the handlers above lands here. The emulator
            # going away is not a bug in the plan - a run with hours
            # left in it should wait for the emulator to come back
            # rather than end on it.
            print("  %s" % error)
            if not adb.wait_for_device():
                print("  emulator did not come back - stopping")
                break
            print("  emulator is back")

    total = time.time() - started
    print("\n%d boards in %.1f min - %.1fs each, %.0f/hour"
          % (wins, total / 60, total / max(wins, 1), 3600 * wins / total))
    return wins


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--count", type=int, default=None,
                        help="stop after this many wins (default: keep going)")
    parser.add_argument("--serial", default=None, help="emulator address")
    parser.add_argument("--quiet", action="store_true",
                        help="only print wins")
    args = parser.parse_args()

    if args.serial:
        config.DEVICE_SERIAL = args.serial
    try:
        run(args.count, verbose=not args.quiet)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
