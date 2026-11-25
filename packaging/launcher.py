"""PyInstaller entry point: the same ``main`` as ``python -m jmc_guitar_zoom``."""

import sys

from jmc_guitar_zoom.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
