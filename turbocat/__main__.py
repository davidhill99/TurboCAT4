import multiprocessing
import sys

from .cli import main

# Guarded: background work (pictures, game details) runs in processes started from this one, and
# each of them imports this file again; they must not open another window.
if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
