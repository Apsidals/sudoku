"""
Solve the one board that is on screen, and stop.

For looking at what the reader sees and what the solver would do,
without committing to a run. `runner.py` is the thing that plays
board after board.

    python main.py --dry-run --debug    read it, solve it, tap nothing
    python main.py                      read it, solve it, play it
"""

import argparse
import sys
import time

import adb
import config
import game
import solver
import vision


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="read and solve, print the answer, tap nothing",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="write debug_plan.png: the lattice and the planned digits",
    )
    parser.add_argument(
        "--serial", default=None,
        help="override the emulator address (default %s)" % config.DEVICE_SERIAL,
    )
    args = parser.parse_args()

    if args.serial:
        config.DEVICE_SERIAL = args.serial
    adb.connect()

    if not adb.is_game_foreground():
        print(
            "refused: %s is not in the foreground (%s is)"
            % (config.GAME_PACKAGE, adb.foreground_package() or "nothing"),
            file=sys.stderr,
        )
        return 1

    started = time.time()
    try:
        played = game.solve_screen(dry_run=args.dry_run, debug=args.debug)
    except (vision.BoardReadError, solver.Unsolvable, RuntimeError) as error:
        print("refused: %s" % error, file=sys.stderr)
        return 1

    if played:
        print("%d cells in %.1fs" % (played, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
