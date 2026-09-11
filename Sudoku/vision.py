"""
Reading the board off a screenshot.

Three things are measured rather than configured: the lattice, the
board's shape, and the digit glyphs.

The lattice, because the board is not in the same place on every
screen, and a hardcoded grid reads the wrong cell without ever saying
it did. The rules are strong enough to find directly - each spans the
whole board, while a digit spans one cell of it - so they are found and
clustered.

The shape, because there is more than one. The game ships a 6x6 "Fast"
mode alongside the 9x9, and its blocks are two rows by three columns.
Both facts are legible in the same picture: the rules that bound a
block are drawn twice as thick as the ones inside it, so counting cells
between thick rules gives the block shape, and counting rules gives the
board size.

The glyphs, because the app's font is not on this machine. The number
pad draws its digits in that same font, which is a set of labelled
examples handed over on every frame - but only of the digits that are
still needed, since the game deletes a key once its digit is fully
placed. So they are cached across runs: see `load_templates`.
"""

import os

import cv2
import numpy as np

import config


class BoardReadError(Exception):
    """The screen could not be read as a board."""


# --- lattice ---

def _runs(mask):
    """[(start, end)] of the True runs in a 1-D boolean array."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def _rules(dark, axis, span, label):
    """
    The grid rules along one axis, as (centre, thickness).

    A rule is a line of dark pixels running most of the way across the
    board; a digit is not. The threshold is on the fraction of the
    crop's other dimension that is dark, which is why the crop has to
    contain the board and little else.
    """
    groups = _runs(dark.sum(axis=axis) > 0.5 * span)
    if len(groups) < 5:
        raise BoardReadError(
            "found %d %s grid rules, too few to be a board"
            % (len(groups), label)
        )
    return [((a + b) / 2.0, b - a + 1) for a, b in groups]


def _block_span(rules, label):
    """
    How many cells lie between block boundaries, along one axis.

    The rules bounding a block are drawn about twice as thick as the
    ones inside it (4px against 2px at this resolution), so the thick
    ones are the block boundaries. Splitting on the midpoint rather
    than on a fixed width keeps this working if the game is ever drawn
    at another scale.
    """
    widths = [w for _, w in rules]
    cut = (min(widths) + max(widths)) / 2.0
    thick = [i for i, (_, w) in enumerate(rules) if w > cut]

    if len(thick) < 2 or thick[0] != 0 or thick[-1] != len(rules) - 1:
        raise BoardReadError(
            "the %s block boundaries do not bound the board (thick rules "
            "at %s of %d)" % (label, thick, len(rules))
        )
    spans = set(np.diff(thick))
    if len(spans) != 1:
        raise BoardReadError(
            "the %s blocks are not all the same width (%s)"
            % (label, sorted(spans))
        )
    return thick, spans.pop()


def find_grid(img):
    """
    Locate the lattice and work out the board's shape.

    Returns a dict of the rule centres per axis ("xs", "ys"), the board
    size, the block dimensions, and the cell pitch.
    """
    region = config.BOARD_REGION
    crop = img[region["top"]:region["bottom"], region["left"]:region["right"]]
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1]

    # Grey and darker than the page. The saturation half of that is
    # what keeps the game's own highlighting out of the profile: when a
    # cell is selected the app floods its whole block, and a flooded
    # block is a third of the board's height in one column. Two of them
    # stacked would clear the "runs most of the way down" test and be
    # counted as an extra rule, which fails the read outright. The
    # rules are neutral grey (saturation 16-31); every fill the game
    # paints is blue (88-119), so the two never meet.
    dark = (
        (grey < config.GRID_LINE_MAX_LUMA)
        & (saturation < config.GRID_LINE_MAX_SATURATION)
    ).astype(np.uint8)

    height, width = dark.shape
    vertical = _rules(dark, 0, height, "vertical")
    horizontal = _rules(dark, 1, width, "horizontal")

    size = len(vertical) - 1
    if len(horizontal) - 1 != size:
        raise BoardReadError(
            "the board is %d cells wide and %d tall, so it is not a board"
            % (size, len(horizontal) - 1)
        )
    if size > config.MAX_BOARD_SIZE:
        raise BoardReadError(
            "a %dx%d board needs digits above %d, which this reads no "
            "templates for" % (size, size, config.MAX_BOARD_SIZE)
        )

    _, block_cols = _block_span(vertical, "vertical")
    _, block_rows = _block_span(horizontal, "horizontal")
    if block_rows * block_cols != size:
        raise BoardReadError(
            "%dx%d blocks do not tile a %d-cell board"
            % (block_rows, block_cols, size)
        )

    xs = np.array([c for c, _ in vertical]) + region["left"]
    ys = np.array([c for c, _ in horizontal]) + region["top"]

    # A board whose cells are not square, or whose two axes disagree on
    # pitch, is not a board - it is a lattice fitted to something else,
    # and every digit read out of it would come from the wrong box.
    pitch_x = float(np.mean(np.diff(xs)))
    pitch_y = float(np.mean(np.diff(ys)))
    if abs(pitch_x - pitch_y) > 0.04 * max(pitch_x, pitch_y):
        raise BoardReadError(
            "cell pitch disagrees between axes: %.1f vs %.1f"
            % (pitch_x, pitch_y)
        )
    spread = max(np.diff(xs).max() - np.diff(xs).min(),
                 np.diff(ys).max() - np.diff(ys).min())
    if spread > 0.06 * pitch_x:
        raise BoardReadError(
            "grid rules are unevenly spaced (spread %.1fpx)" % spread
        )

    return {
        "xs": xs,
        "ys": ys,
        "size": size,
        "block_rows": block_rows,
        "block_cols": block_cols,
        "pitch": (pitch_x + pitch_y) / 2.0,
    }


def cell_centre(grid, row, col):
    """Screen coordinates of the middle of cell (row, col)."""
    x = (grid["xs"][col] + grid["xs"][col + 1]) / 2.0
    y = (grid["ys"][row] + grid["ys"][row + 1]) / 2.0
    return int(round(x)), int(round(y))


# --- glyphs ---

GLYPH_H = 32  # every glyph is scaled to this height before comparison


def _normalise(mask):
    """
    A binary glyph, scaled to a fixed height and centred in a fixed box.

    Height rather than area, and the aspect ratio is kept, because 1 is
    half the width of the other eight and stretching it to a square
    throws away the one cue that identifies it outright.
    """
    rows, cols = np.nonzero(mask)
    if len(rows) == 0:
        return None
    glyph = mask[rows.min():rows.max() + 1, cols.min():cols.max() + 1]

    scale = GLYPH_H / glyph.shape[0]
    width = max(1, int(round(glyph.shape[1] * scale)))
    glyph = cv2.resize(
        glyph.astype(np.uint8) * 255, (width, GLYPH_H),
        interpolation=cv2.INTER_AREA,
    )
    glyph = (glyph > 127).astype(np.float32)

    canvas = np.zeros((GLYPH_H, GLYPH_H), np.float32)
    width = min(width, GLYPH_H)
    left = (GLYPH_H - width) // 2
    canvas[:, left:left + width] = glyph[:, :width]
    return canvas


def _similarity(a, b):
    """Intersection over union of two normalised glyphs."""
    intersection = float(np.minimum(a, b).sum())
    union = float(np.maximum(a, b).sum())
    return intersection / union if union else 0.0


def _holes(mask):
    """
    How many enclosed background regions a glyph has.

    Shape alone does not separate 3 from 8 in this font: normalised and
    overlaid they score 0.62 and 0.60, a margin of 0.025, which is not
    a margin at all - and a 3 entered as an 8 is a mistake the game
    counts against the three it allows. Topology separates them
    outright, and does not care about stroke weight, which is the one
    thing that really does differ between the pad's glyphs and the
    board's. Measured on the cell rather than on the normalised copy,
    so the resize cannot pinch a loop shut.

    In this font: 8 has two, {4, 6, 9} have one, {1, 2, 3, 5, 7} none.
    Nothing here assumes that - the counts are measured off the pad
    alongside the templates.
    """
    if mask.size == 0:
        return 0
    padded = np.pad(mask.astype(np.uint8), 1)
    count, labels = cv2.connectedComponents(
        (1 - padded).astype(np.uint8), connectivity=4
    )
    touching = set(labels[0, :]) | set(labels[-1, :])
    touching |= set(labels[:, 0]) | set(labels[:, -1])
    return len([i for i in range(1, count) if i not in touching])


def _classify(glyph, holes, templates):
    """
    (digit, margin) for one glyph against the templates.

    Only templates with the glyph's own topology are eligible. If none
    is - a smudged loop, an unexpected font - fall back to the whole
    set rather than refuse outright, and let the margin say how much to
    trust the answer.

    The margin is over the runner-up, not the raw overlap, because the
    pad's glyphs are drawn a shade lighter than the board's: even a
    certain match only overlaps about 0.75, and a threshold on that
    would refuse every board there is.
    """
    eligible = {d: t for d, (t, h) in templates.items() if h == holes}
    if not eligible:
        eligible = {d: t for d, (t, _) in templates.items()}

    scores = sorted(
        ((_similarity(glyph, t), d) for d, t in eligible.items()),
        reverse=True,
    )
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    return scores[0][1], scores[0][0] - runner_up


# --- the number pad ---

def pad_keys(img, templates=None, size=None):
    """
    The number pad: which digit each key is, and where to tap it.

    A key cannot be identified by counting from the left, because the
    game deletes a key outright once its digit is fully placed and
    leaves the gap behind - with 2, 8 and 9 gone, the sixth key from
    the left is a 7. Nor by its position, because a 6x6 board's pad has
    six wider keys on a different pitch from the 9x9's nine.

    So the keys are read, not counted: each glyph is classified against
    the cached templates, the same way a board cell is. That leaves one
    cold start to handle - the very first run, with nothing cached -
    and there the pad must be full, so the keys can be labelled by
    position and the templates taken from them.

    Returns {digit: (x, y)} and {digit: (glyph, holes)} for the keys on
    screen.
    """
    region = config.PAD_REGION
    crop = img[region["top"]:region["bottom"], region["left"]:region["right"]]
    blue = crop[:, :, 0].astype(int)
    red = crop[:, :, 2].astype(int)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ink = ((blue - red) > 40) & (grey < 220)

    columns = _runs(ink.sum(axis=0) > 0)
    if not columns:
        raise BoardReadError("no number-pad keys on screen")

    keys = []
    for left, right in columns:
        column = ink[:, left:right + 1]
        rows = _runs(column.sum(axis=1) > 0)
        if not rows:
            continue
        # Each key also carries a small "how many are left" count under
        # the digit. The digit is the tallest run; take that one only.
        top, bottom = max(rows, key=lambda run: run[1] - run[0])
        patch = column[top:bottom + 1, :]
        glyph = _normalise(patch)
        if glyph is None:
            continue
        keys.append((
            glyph,
            _holes(patch),
            (int(region["left"] + (left + right) / 2),
             int(region["top"] + (top + bottom) / 2)),
        ))

    if not keys:
        raise BoardReadError("the number pad has no legible keys")

    if templates:
        labelled = {}
        found = {}
        for glyph, holes, centre in keys:
            digit, margin = _classify(glyph, holes, templates)
            if margin < config.MIN_PAD_MARGIN:
                raise BoardReadError(
                    "a number-pad key read as %d at only %.2f margin"
                    % (digit, margin)
                )
            if digit in labelled:
                raise BoardReadError(
                    "two number-pad keys both read as %d" % digit
                )
            labelled[digit] = centre
            found[digit] = (glyph, holes)
        # The pad is drawn in ascending order, so a labelling that is
        # not ascending left to right is a misread, whatever its
        # margins said.
        order = [d for d, _ in sorted(labelled.items(), key=lambda kv: kv[1][0])]
        if order != sorted(order):
            raise BoardReadError(
                "the number pad reads as %s, which is not in order" % order
            )
        return labelled, found

    if size is None or len(keys) != size:
        raise BoardReadError(
            "nothing is cached to read the number pad with, and it is not "
            "full (%d keys on a %s board), so its keys cannot be named. "
            "Start a fresh puzzle once to record them."
            % (len(keys), size if size else "?")
        )
    centres = {i + 1: centre for i, (_, _, centre) in enumerate(keys)}
    found = {i + 1: (glyph, holes) for i, (glyph, holes, _) in enumerate(keys)}
    return centres, found


def has_cache():
    """Whether any templates have been recorded yet."""
    return os.path.exists(config.TEMPLATE_CACHE)


def load_templates(found, size):
    """
    Every digit template this board needs, topping the cache up from
    what is on the pad now and saving anything new.

    The glyphs are font constants: identical on every frame, every
    puzzle and every run. The pad is only where they are quarried, and
    it runs out of them as the board fills, so they are kept.
    """
    cached = {}
    if os.path.exists(config.TEMPLATE_CACHE):
        with np.load(config.TEMPLATE_CACHE) as saved:
            for digit in range(1, config.MAX_BOARD_SIZE + 1):
                if ("glyph%d" % digit) in saved:
                    cached[digit] = (
                        saved["glyph%d" % digit],
                        int(saved["holes%d" % digit]),
                    )

    fresh = {d: v for d, v in found.items() if d not in cached}
    if fresh:
        cached.update(fresh)
        flat = {}
        for digit, (glyph, holes) in cached.items():
            flat["glyph%d" % digit] = glyph
            flat["holes%d" % digit] = holes
        np.savez_compressed(config.TEMPLATE_CACHE, **flat)

    missing = [d for d in range(1, size + 1) if d not in cached]
    if missing and found is not None:
        raise BoardReadError(
            "no template for %s: those keys are already gone from the pad "
            "and nothing is cached for them. Open a fresh puzzle once, "
            "with every key up, to record them."
            % ", ".join(str(d) for d in missing)
        )
    return {d: cached[d] for d in range(1, size + 1)}


# --- the board ---

def _ink_mask(cell):
    """
    The digit in a cell, as a boolean mask.

    Ink is found by distance from the cell's own background rather than
    by absolute darkness, because a cell's background is not always
    white. Selecting a cell tints its row, column and block pale grey,
    and tints every cell holding the selected digit pale blue; a plain
    "darker than 160" test reads the tint itself as ink and loses the
    digit inside it. Sampling the background per cell costs nothing and
    makes all three cases the same case.

    The background is the median colour, which is safe because a digit
    covers well under half of the inset crop, so the median is always a
    background pixel.
    """
    flat = cell.reshape(-1, 3).astype(np.int16)
    background = np.median(flat, axis=0)
    distance = np.sqrt(((flat - background) ** 2).sum(axis=1))
    return (distance > config.INK_MIN_DISTANCE).reshape(cell.shape[:2])


def _cell_crop(img, grid, row, col):
    """The inset interior of one cell."""
    x0, x1 = grid["xs"][col], grid["xs"][col + 1]
    y0, y1 = grid["ys"][row], grid["ys"][row + 1]
    pad_x = (x1 - x0) * config.CELL_INSET
    pad_y = (y1 - y0) * config.CELL_INSET
    return img[
        int(round(y0 + pad_y)):int(round(y1 - pad_y)),
        int(round(x0 + pad_x)):int(round(x1 - pad_x)),
    ]


def read_cell(img, grid, templates, row, col):
    """
    One cell's digit, or 0 if it is empty. No confidence check.

    Used to confirm that the first move of a plan landed, which is a
    question about one cell and does not need the other eighty read to
    answer it.
    """
    cell = _cell_crop(img, grid, row, col)
    if cell.size == 0:
        raise BoardReadError("cell (%d,%d) crops to nothing" % (row, col))
    ink = _ink_mask(cell)
    if ink.mean() < config.MIN_INK_FRACTION:
        return 0
    glyph = _normalise(ink)
    if glyph is None:
        return 0
    return _classify(glyph, _holes(ink), templates)[0]


def read_board(img, grid, templates, min_confidence=None):
    """
    The board's digits, 0 for an empty cell.

    Returns (digits, confidence), the confidence being each cell's
    classification margin, so a doubtful read can refuse rather than
    guess: one wrong digit tapped in is a mistake the game counts, and
    three of those end the puzzle.
    """
    if min_confidence is None:
        min_confidence = config.MIN_CELL_MARGIN
    size = grid["size"]
    digits = np.zeros((size, size), np.int8)
    confidence = np.ones((size, size), np.float32)

    for row in range(size):
        for col in range(size):
            cell = _cell_crop(img, grid, row, col)
            if cell.size == 0:
                raise BoardReadError("cell (%d,%d) crops to nothing" % (row, col))

            ink = _ink_mask(cell)
            if ink.mean() < config.MIN_INK_FRACTION:
                continue  # empty

            glyph = _normalise(ink)
            if glyph is None:
                continue
            digit, margin = _classify(glyph, _holes(ink), templates)
            digits[row, col] = digit
            confidence[row, col] = margin

    worst = float(confidence.min())
    if worst < min_confidence:
        where = np.unravel_index(int(np.argmin(confidence)), confidence.shape)
        raise BoardReadError(
            "cell (%d,%d) read as %d at only %.2f margin"
            % (where[0], where[1], digits[where], worst)
        )
    return digits, confidence


def format_board(digits, grid=None):
    """The board as text, for logs."""
    digits = np.asarray(digits)
    size = digits.shape[0]
    block = grid["block_cols"] if grid else int(round(size ** 0.5))
    rule_every = grid["block_rows"] if grid else block

    lines = []
    for row in range(size):
        cells = [str(d) if d else "." for d in digits[row]]
        chunks = [
            " ".join(cells[i:i + block]) for i in range(0, size, block)
        ]
        lines.append(" | ".join(chunks))
        if (row + 1) % rule_every == 0 and row + 1 < size:
            lines.append("-" * len(lines[-1]))
    return "\n".join(lines)
