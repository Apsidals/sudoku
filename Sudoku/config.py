"""
Calibration constants for the Sudoku bot.

Almost nothing here is a pixel coordinate for the board itself. The
grid is measured from the screenshot every pass (see vision.find_grid),
because the board's position shifts a little between the puzzle screen
and the "daily challenge" screen, and a hardcoded lattice would read
the wrong cells on one of them without ever saying so.

What is hardcoded is the stuff outside the board: the number pad and
the tool row, which sit at fixed offsets from the bottom of the screen.
"""

import os

# --- ADB / emulator ---
ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
DEVICE_SERIAL = "127.0.0.1:5575"

# "Sudoku - Free Classic Puzzle" by Meevii. Used to tell whether the
# game is still in the foreground before tapping anything into it.
GAME_PACKAGE = "easy.sudoku.puzzle.solver.free"

# The activity to relaunch when a screen cannot be got out of any other
# way. Starting it drops an ad, a web view or a store page on the floor
# without having to understand, or click, any part of it.
GAME_ACTIVITY = "com.meevii.ui.activity.MainActivity"

# The other two activities the loop passes through, by short name.
# Navigation keys off these rather than off what the screen looks like,
# because the activity is already correct during the second or so where
# a screen is fading in and the pixels are not yet anything.
RESULT_ACTIVITY = "GameResultActivity"
BOARD_ACTIVITY = "MainActivity"
HOME_ACTIVITY = "HomeActivity"

# Portrait. `wm size` reports this transposed; the screencap is 1080x1920.
SCREEN_W = 1080
SCREEN_H = 1920

# --- Debug output ---
# Every pass overwrites these, and this tree is inside OneDrive, so the
# default of "." means each rewrite is queued for upload again. Point
# SUDOKU_DEBUG_DIR at scratch for a long run.
DEBUG_DIR = os.environ.get("SUDOKU_DEBUG_DIR", ".")


def debug_path(name: str) -> str:
    """Where to write a debug image called `name`."""
    if DEBUG_DIR and DEBUG_DIR != ".":
        os.makedirs(DEBUG_DIR, exist_ok=True)
        return os.path.join(DEBUG_DIR, name)
    return name


# --- Board search region ---
# The band of the screen the 9x9 board can appear in, in device pixels.
# Deliberately generous: it only has to exclude the number pad and the
# header, because find_grid measures the real edges inside it.
BOARD_REGION = {
    "left": 0,
    "top": 340,
    "right": 1080,
    "bottom": 1300,
}

# --- Number pad ---
# Nine keys in a row along the bottom, 1..9 left to right.
PAD_REGION = {
    "left": 100,
    "top": 1570,
    "right": 980,
    "bottom": 1720,
}

# Where the digit templates are cached between runs.
#
# They have to be cached, because they are cut from the number pad and
# the pad loses keys as the board fills. A puzzle resumed with its 2s
# already placed has no 2 key, so no 2 template, and every 2 on the
# board would be matched against the eight glyphs that are left and
# come back as whichever of them fits worst-but-best. The font does not
# change between runs or between puzzles, so one full pad ever is
# enough for all of them.
TEMPLATE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "templates.npz")

# --- Ink ---
# Board digits are near-black; the ones the player has entered are blue.
# Both are far from the white cell background, and the solver does not
# care which is which, so segmentation is by distance from background
# and the colour is only used to tell "given" from "entered" in debug
# output.
# How far a pixel must sit from its cell's own background colour, in
# BGR euclidean distance, to count as ink. Dark text on white is 352
# away and dark text on the game's pale-blue highlight is 250, so the
# threshold has plenty of room below both; the thin grid rules are 117
# from white, which is why it sits above that as well - CELL_INSET is
# what really keeps the rules out, and this is the second fence.
INK_MIN_DISTANCE = 130

GRID_LINE_MAX_LUMA = 200        # a grid rule is darker than this ...
GRID_LINE_MAX_SATURATION = 45   # ... and greyer than this

# The largest board this can read. The game also offers a 16x16 mode,
# whose cells hold 10 to 16 - two glyphs in the space of one, which
# nothing here is built to read. Refusing it by size is honest; trying
# it would enter wrong digits into a real puzzle.
MAX_BOARD_SIZE = 9

# How far the best digit match must beat the runner-up before it is
# acted on. A correct match on this font typically clears 0.29 on a
# board cell, and pad keys are cut from the same source as the
# templates so they clear much more.
MIN_CELL_MARGIN = 0.08
MIN_PAD_MARGIN = 0.08

# A cell is treated as empty if fewer than this fraction of its inner
# area is ink. An empty cell is not perfectly clean: the grid rules
# clip into the crop, which is why the sample window is inset first.
MIN_INK_FRACTION = 0.01

# How far inside each cell to sample, as a fraction of cell size. Big
# enough to clear the grid rules on both the thin and the thick (3x3
# block) lines, small enough to keep the whole glyph.
CELL_INSET = 0.16

# --- Tapping ---
TAP_SETTLE_MS = 90    # after a cell tap, before the digit tap
MOVE_SETTLE_MS = 140  # after a completed move, before the next one


# --- the run ---
# Which row to pick on the New Game sheet. Matched against the sheet's
# own text, so it is whatever the game calls it: Beginner, Easy, Medium,
# Hard, Expert, Extreme, Fast.
#
# Beginner is the default because the goal here is a count of wins, and
# a win is a win: a Beginner board ships about fifty of its eighty-one
# cells already filled, so it costs roughly thirty moves against the
# fifty an Easy board needs, at the same one win each.
DIFFICULTY = "Beginner"

# The two taps that get from a finished board to the next one. Both
# were read out of the widget tree once and do not move: New Game at
# the foot of the result card, then the Beginner row on the sheet it
# opens. Tapping fixed points rather than looking them up each time is
# what keeps a board's overhead near a second instead of six.
NEW_GAME_BUTTON = (540, 1735)
DIFFICULTY_ROW = (540, 1175)

# The game's own back arrow, top left of every board. Used only to
# abandon a board that will not read.
BOARD_BACK_ARROW = (50, 63)

# How long to give each of the two taps.
#
# Both used to be much longer, from when the taps were posted blind and
# a wait that came up short cost a whole wasted pass round the loop.
# start_next now checks that the sheet really opened before it picks a
# difficulty, and the loop waits for a board to finish drawing rather
# than assuming it has, so these only have to cover the animation
# itself rather than the worst case behind it.
SHEET_WAIT_MS = 550
BOARD_WAIT_MS = 700

# How many boards may be refused before the run gives up rather than
# hammering a screen it cannot read. Refusals are expected now and
# then; a steady stream of them means something changed.
MAX_FAILURES = 25

# A "way out of this screen" bigger than this is not a close button, it
# is the dim behind the dialog - which is clickable, covers everything,
# and on the screens where it does not dismiss is a tap straight into
# whatever is being advertised.
MAX_DISMISS_AREA = 400 * 400
