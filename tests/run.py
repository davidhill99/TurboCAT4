"""Run all of TurboCAT's tests and exit with their result.

python tests/run.py is the same as python -m unittest discover -s tests -v, except that it exits
straight after the tests instead of going through Python's own shut-down: on some systems Qt crashes
there ("shared QObject was deleted directly", exit 139) after every test has passed, which would
make a good run look like a failure."""
import os
import sys
import unittest

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(here), here]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Guarded: background work runs in processes that import this file again (test_jobs.py); they must
# not run the tests themselves.
if __name__ == "__main__":
    result = unittest.main(module=None, argv=[sys.argv[0], "discover", "-s", here, "-v"], exit=False).result
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)
