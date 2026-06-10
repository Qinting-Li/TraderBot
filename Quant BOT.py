"""Compatibility launcher for the TraderBot package.

Prefer:
    python -m traderbot
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from traderbot.app import run


if __name__ == "__main__":
    run()
