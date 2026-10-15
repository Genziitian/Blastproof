from __future__ import annotations

import logging
import os


def setup(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or os.getenv("LOG_LEVEL") or "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
