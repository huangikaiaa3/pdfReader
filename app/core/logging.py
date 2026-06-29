"""Logging helpers for API and worker processes."""

from __future__ import annotations

import logging


def setup_logging(log_level: str) -> None:
    """Configure a consistent process-wide logging format."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
