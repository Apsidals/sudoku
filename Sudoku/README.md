# Sudoku

Plays *Sudoku - Free Classic Puzzle* (`easy.sudoku.puzzle.solver.free`)
on a BlueStacks emulator over ADB: reads the board off a screenshot,
solves it exactly, taps the answer in, and starts the next one.

    python runner.py                # play Beginner boards until stopped
    python runner.py --count 50     # ... or fifty of them
    python main.py --dry-run --debug   # read and solve one board, tap nothing

Measured on this setup: **about 200 boards an hour**, 18 seconds each,
which puts 3000 wins at roughly 15 hours.

The emulator must be reachable first:

    "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" connect 127.0.0.1:5575

## How it reads the board

Three things are measured from the picture rather than written down,
because each of them varies and a hardcoded value would be wrong
without ever saying so.

**The lattice.** The grid rules are found directly - each spans the
whole board, while a digit spans one cell of it - and clustered into
rule centres. A board whose two axes disagree on cell pitch is refused
rather than read out of the wrong boxes.

**The board's shape.** There is more than one: the game ships a 6x6
"Fast" mode whose blocks are two rows by three columns. The rules that
bound a block are drawn twice as thick as the ones inside it, so
counting rules gives the size and counting cells between thick rules
gives the block shape. Both 6x6 and 9x9 work; 16x16 is refused, because
its cells hold two glyphs and nothing here reads those.

**The digits.** The app's font is not on this machine, so the templates
are cut from the number pad, which draws the same font. Two wrinkles:
the pad deletes a key once its digit is fully placed, so keys are
identified by classifying them rather than by counting from the left;
and a board resumed with its 2s already placed has no 2 key to learn
from, so templates are cached in `templates.npz` across runs.

Classification is normalised-glyph overlap, with one extra feature that
does the real work. Shape alone does not separate 3 from 8 in this
font - overlaid they score 0.62 and 0.60, a margin of 0.025 - so the
number of enclosed holes in the glyph is used as a hard filter first.
That takes the worst margin on a real board from 0.025 to 0.29.

Ink is found by distance from each cell's own background colour, not by
absolute darkness, because the background is not always white: selecting
a cell tints its row, column and block grey and every cell holding the
same digit blue.

## What it refuses to do

The solver is also the reader's proof. A misread board usually shows up
as one that cannot be solved, or one that can be solved two ways - and
this game does not ship ambiguous puzzles, so a second solution means a
digit was missed. Either is refused rather than guessed at, because a
wrong digit is a mistake the game counts and three of them lose the
board.

On top of that: a cell read at a thin margin refuses, and the first
move of every board is played alone and checked before the rest is
posted. That one screenshot catches pencil mode left on, a stale
lattice, a mis-measured pad, and the game not being in front.

A board that still will not read after settling is abandoned, not
guessed at.

## How it gets between boards

Two taps at fixed coordinates: New Game on the result card, then the
Beginner row on the sheet it opens. `start_next` checks the sheet
actually opened before picking a difficulty - a stray tap at the New
Game position while the sheet is up lands on "Fast" and quietly starts
a 6x6 game.

Anything else on screen gets `recover()`: a close button if the widget
tree offers one, then the back key, then a relaunch of the game's own
activity. Nothing here tries to understand an ad. The relaunch is the
way out that always works, and it never taps into one on purpose - the
"small unlabelled button in a corner" guess is only used on screens
that do not belong to the game, because inside it that guess finds the
back arrow and the settings gear.

A win is counted when the result screen appears, not when the moves are
posted. Those are not the same thing: a tap can miss, and the game also
finishes a board itself once the rest is forced.

## Files

| | |
|---|---|
| `config.py`  | every calibrated constant, with why it is that value |
| `adb.py`     | screenshots, taps, keys. Taps go out in bulk: chaining them into one shell call is 107ms each instead of 167ms |
| `vision.py`  | lattice, board shape, digit templates, reading cells |
| `solver.py`  | constraint propagation and search, for any block geometry |
| `game.py`    | read, solve and play one board |
| `ui.py`      | the widget tree, for the screens that are not the board |
| `runner.py`  | the loop |
| `main.py`    | solve the one board on screen, and stop |

`templates.npz` is the digit cache. Deleting it costs nothing but a
fresh puzzle to re-learn from.
