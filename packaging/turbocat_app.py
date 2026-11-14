"""The packaged TurboCAT's starting point: opens the window (or runs a command, if given one)."""
import os
import sys

from turbocat import paths
from turbocat.cli import main

if __name__ == "__main__":
    args = sys.argv[1:] or ["window"]
    os.makedirs(os.path.dirname(paths.default_db()), exist_ok=True)     # first start on Windows/macOS
    sys.exit(main(args))
