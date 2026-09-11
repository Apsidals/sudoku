"""
Solving the grid.

Constraint propagation first, search only for what propagation cannot
finish. The propagation is the usual pair: a cell with one candidate
left takes it, and a unit whose digit has one home left puts it there.

Nothing here is 9x9. The game ships a 6x6 "Fast" mode whose blocks are
two rows by three columns, and a shape is a shape - so the units are
built from a measured (size, block_rows, block_cols) rather than
written down. `Shape` caches that construction, because the board is
read many times per puzzle and the unit tables only depend on those
three numbers.

The solver is also the reader's proof. A board read off a screenshot
can be wrong in a way no confidence score catches - a 6 read as a 5 in
a cell whose real digit is legible enough to score well - and the way
that shows up is a puzzle that is unsolvable, or one with more than one
solution. So `solve` reports both, and the caller refuses to tap on
either rather than entering a mistake the game counts.
"""

import numpy as np


class Unsolvable(Exception):
    """The board as read admits no solution, so it was read wrong."""


class Shape:
    """The unit structure of one board geometry, built once and reused."""

    _cache = {}

    def __new__(cls, size, block_rows, block_cols):
        key = (size, block_rows, block_cols)
        if key in cls._cache:
            return cls._cache[key]
        if block_rows * block_cols != size:
            raise ValueError(
                "a %dx%d block cannot tile a board of %d digits"
                % (block_rows, block_cols, size)
            )
        self = super().__new__(cls)
        self.size = size
        self.block_rows = block_rows
        self.block_cols = block_cols
        self.digits = frozenset(range(1, size + 1))

        units = []
        for row in range(size):
            units.append([(row, c) for c in range(size)])
        for col in range(size):
            units.append([(r, col) for r in range(size)])
        for top in range(0, size, block_rows):
            for left in range(0, size, block_cols):
                units.append([
                    (top + r, left + c)
                    for r in range(block_rows) for c in range(block_cols)
                ])
        self.units = units
        self.units_of = {
            (r, c): [u for u in units if (r, c) in u]
            for r in range(size) for c in range(size)
        }
        self.peers = {
            cell: {p for u in unit_list for p in u if p != cell}
            for cell, unit_list in self.units_of.items()
        }

        cls._cache[key] = self
        return self


def _assign(shape, candidates, cell, digit):
    """
    Place `digit` in `cell` and propagate. Returns False on contradiction.

    Propagation is eliminate-and-cascade: taking a digit out of a peer
    can leave that peer with one candidate (place it), and can leave a
    unit with one home for some digit (place that too).
    """
    for other in candidates[cell] - {digit}:
        if not _eliminate(shape, candidates, cell, other):
            return False
    return True


def _eliminate(shape, candidates, cell, digit):
    if digit not in candidates[cell]:
        return True
    candidates[cell] = candidates[cell] - {digit}

    if not candidates[cell]:
        return False  # took the last candidate away from a cell
    if len(candidates[cell]) == 1:
        only = next(iter(candidates[cell]))
        for peer in shape.peers[cell]:
            if not _eliminate(shape, candidates, peer, only):
                return False

    for unit in shape.units_of[cell]:
        homes = [c for c in unit if digit in candidates[c]]
        if not homes:
            return False  # the digit has nowhere left in this unit
        if len(homes) == 1:
            if not _assign(shape, candidates, homes[0], digit):
                return False
    return True


def _candidates_from(shape, digits):
    """Propagate the givens. Returns None if they contradict."""
    size = shape.size
    candidates = {
        (r, c): shape.digits for r in range(size) for c in range(size)
    }
    for row in range(size):
        for col in range(size):
            digit = int(digits[row][col])
            if digit and not _assign(shape, candidates, (row, col), digit):
                return None
    return candidates


def _search(shape, candidates, limit, found):
    """
    Depth-first over the most constrained cell, stopping at `limit`
    solutions. Appends to `found`; returns when it is full.
    """
    if len(found) >= limit:
        return
    unsolved = [c for c in candidates if len(candidates[c]) > 1]
    if not unsolved:
        grid = np.zeros((shape.size, shape.size), np.int8)
        for (row, col), options in candidates.items():
            grid[row, col] = next(iter(options))
        found.append(grid)
        return

    cell = min(unsolved, key=lambda c: len(candidates[c]))
    for digit in sorted(candidates[cell]):
        branch = dict(candidates)
        if _assign(shape, branch, cell, digit):
            _search(shape, branch, limit, found)
        if len(found) >= limit:
            return


def solve(digits, shape, want_uniqueness=True):
    """
    Solve the board.

    Returns (solution, unique). `unique` is False when a second
    solution exists, which on a real puzzle means the board was misread
    rather than that the puzzle is ambiguous - this game only ships
    puzzles with one answer.

    Raises Unsolvable when there is no solution at all.
    """
    candidates = _candidates_from(shape, digits)
    if candidates is None:
        raise Unsolvable("the givens contradict each other")

    found = []
    _search(shape, candidates, 2 if want_uniqueness else 1, found)
    if not found:
        raise Unsolvable("no arrangement completes this board")
    return found[0], len(found) == 1


def moves_for(digits, solution, shape):
    """
    The cells to fill, as (row, col, digit), easiest first.

    Order matters for more than tidiness. An entry that is wrong costs
    one of the three mistakes the game allows, so the early taps should
    be the ones an independent solver would also make: the cell whose
    digit is forced by the fewest remaining unknowns goes first. A
    misread board then tends to fail on a cell that can still be
    checked cheaply rather than deep into a run.
    """
    size = shape.size
    filled = np.array(digits, dtype=np.int8).copy()
    remaining = {
        (r, c) for r in range(size) for c in range(size)
        if not int(digits[r][c])
    }

    def freedom(cell):
        taken = {int(filled[p]) for p in shape.peers[cell]} - {0}
        return len(shape.digits - taken)

    ordered = []
    while remaining:
        cell = min(remaining, key=freedom)
        row, col = cell
        ordered.append((row, col, int(solution[row][col])))
        filled[row, col] = solution[row][col]
        remaining.discard(cell)
    return ordered
