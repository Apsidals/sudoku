"""
Playing one board.

Read it, solve it, tap it in.

The whole approach turns on one property of this game: a move is
self-contained. Tapping a cell and then a number-pad key enters that
digit there, and nothing about it depends on what was tapped before. So
the board is read once, solved once, and the moves are played from that
one plan - no re-reading between moves, no state to drift, and the taps
can be posted in bulk. A tap that misses costs exactly the cell it was
for.

That bulk matters. Every `input tap` costs the device about 105ms of
process startup whatever it does, and a separate adb call adds another
60ms of round trip on top; chaining them into one shell command is the
difference between 167ms and 107ms a tap, which over a fifty-cell board
is five seconds, and over three thousand boards is four hours.

What the run refuses to do is more interesting than what it does:

  - refuse a board it read at a thin margin (vision.read_board)
  - refuse a board whose read admits no solution, which means the read
    was wrong, not that the puzzle is hard (solver.solve)
  - refuse a board with two solutions, which also means the read was
    wrong: this game does not ship ambiguous puzzles, so a second
    solution is a digit that was missed
  - refuse to post the rest of the plan until the first move is seen to
    have landed as the digit intended

That last one is the cheap catch-all. It costs one screenshot and it
catches pencil mode being left on, a stale lattice, a mis-measured
number pad and the game not being in front - each of which would
otherwise spend a hundred taps writing rubbish into a real puzzle.
"""

import time

import cv2
import numpy as np

import adb
import config
import solver
import vision


class Board:
    """A board that has been read and solved, ready to play."""

    def __init__(self, grid, templates, pad_centres, digits, solution, moves):
        self.grid = grid
        self.templates = templates
        self.pad_centres = pad_centres
        self.digits = digits
        self.solution = solution
        self.moves = moves

    @property
    def size(self):
        return self.grid["size"]


def stable_screenshot(tries=8, settle_ms=140):
    """
    A screenshot with no animation running in the board region.

    Placing a digit sets off about a second of highlighting: the block
    floods dark blue with the digits knocked out in white, then fades
    to a pale tint. Read mid-fade, a cell can come back empty when it
    is not - the read is not wrong about the digit, it just cannot see
    one - and an empty that is not empty is the one error the solver
    cannot catch, because a board with a digit missing usually still
    solves. So wait for two identical frames instead.
    """
    region = config.BOARD_REGION
    previous = None
    img = None
    for _ in range(tries):
        img = adb.screenshot()
        board = img[
            region["top"]:region["bottom"], region["left"]:region["right"]
        ]
        if previous is not None and np.array_equal(previous, board):
            return img
        previous = board
        adb.sleep_ms(settle_ms)
    # Nothing settled. Hand back the last frame and let read_board's own
    # margin check decide whether it is legible.
    return img


def read(img):
    """
    Read and solve the board in `img`.

    Raises vision.BoardReadError if the screen is not a legible board,
    and solver.Unsolvable if what was read cannot be a real puzzle.
    """
    grid = vision.find_grid(img)
    size = grid["size"]

    templates = None
    if vision.has_cache():
        templates = vision.load_templates({}, size)
    pad_centres, found = vision.pad_keys(img, templates, size)
    templates = vision.load_templates(found, size)

    digits, _ = vision.read_board(img, grid, templates)
    shape = solver.Shape(size, grid["block_rows"], grid["block_cols"])

    solution, unique = solver.solve(digits, shape)
    if not unique:
        raise solver.Unsolvable(
            "the board as read has more than one solution, so a digit was "
            "missed - refusing to tap a guess in"
        )
    moves = solver.moves_for(digits, solution, shape)
    return Board(grid, templates, pad_centres, digits, solution, moves)


def _taps_for(board, moves):
    """The tap sequence for a run of moves: cell, digit, cell, digit."""
    points = []
    for row, col, digit in moves:
        points.append(vision.cell_centre(board.grid, row, col))
        points.append(board.pad_centres[digit])
    return points


def play(board, verbose=False, chunk=15):
    """
    Play the plan. Returns how many moves were posted.

    Moves go out in chunks with a look at the screen between them, for
    one reason: the game finishes a board itself once every empty cell
    has only one candidate left, and when it does, the board is
    replaced by the result screen mid-plan. The remaining taps would
    then land on whatever that screen has at those coordinates. Nothing
    there is destructive, but the run would have to find its way back
    from a screen it did not mean to open, and noticing costs one
    screenshot per chunk instead.
    """
    if not board.moves:
        return 0

    # The first move alone, then look. Everything that could be wrong
    # about the plan as a whole is wrong about this one move too.
    row, col, digit = board.moves[0]
    adb.tap_sequence(_taps_for(board, board.moves[:1]))

    landed = _confirm(board, row, col, digit)
    if landed != digit:
        raise RuntimeError(
            "first move did not land: (%d,%d) should read %d, reads %s. "
            "Pencil mode left on, or the board is not where it was."
            % (row, col, digit, landed or "empty")
        )

    posted = 1
    rest = board.moves[1:]
    for start in range(0, len(rest), chunk):
        batch = rest[start:start + chunk]
        adb.tap_sequence(_taps_for(board, batch))
        posted += len(batch)
        if start + chunk >= len(rest):
            break
        if not _board_still_up(board):
            if verbose:
                print("    board finished itself after %d moves" % posted)
            break
    return posted


def _confirm(board, row, col, digit, tries=4):
    """
    What one cell reads as, once the screen stops moving.

    Retried rather than read once, because the entry animation can
    cover the cell it is celebrating: mid-flood the digit is white on
    dark blue and the cell reads as empty. An empty here would abort a
    plan that is in fact fine, so it is given a few frames to settle
    before being believed.
    """
    value = 0
    for attempt in range(tries):
        adb.sleep_ms(260 if attempt == 0 else config.TAP_SETTLE_MS)
        try:
            value = vision.read_cell(
                adb.screenshot(), board.grid, board.templates, row, col
            )
        except vision.BoardReadError:
            continue
        if value == digit:
            return value
    return value


def _board_still_up(board):
    """Is the puzzle still on screen, with the same lattice?"""
    try:
        grid = vision.find_grid(adb.screenshot())
    except vision.BoardReadError:
        return False
    return grid["size"] == board.size


def solve_screen(dry_run=False, debug=False, verbose=True):
    """Read, solve and play whatever board is on screen."""
    img = stable_screenshot()
    board = read(img)

    if verbose:
        print(vision.format_board(board.digits, board.grid))
        print(
            "%dx%d board, %d given, %d to fill"
            % (board.size, board.size,
               int((board.digits > 0).sum()), len(board.moves))
        )
    if debug:
        print("wrote %s" % save_overlay(img, board))
    if dry_run:
        print(vision.format_board(board.solution, board.grid))
        return 0
    return play(board, verbose=verbose)


def save_overlay(img, board, name="debug_plan.png"):
    """The plan drawn over the screenshot: read digits vs ones to add."""
    canvas = img.copy()
    grid = board.grid
    for row in range(board.size):
        for col in range(board.size):
            x, y = vision.cell_centre(grid, row, col)
            if board.digits[row][col]:
                cv2.circle(canvas, (x, y), 6, (0, 160, 0), -1)
            else:
                cv2.putText(
                    canvas, str(int(board.solution[row][col])), (x - 18, y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3,
                )
    for x in grid["xs"]:
        cv2.line(canvas, (int(x), int(grid["ys"][0])),
                 (int(x), int(grid["ys"][-1])), (255, 0, 255), 1)
    for y in grid["ys"]:
        cv2.line(canvas, (int(grid["xs"][0]), int(y)),
                 (int(grid["xs"][-1]), int(y)), (255, 0, 255), 1)
    path = config.debug_path(name)
    cv2.imwrite(path, canvas)
    return path
