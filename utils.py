"""Shared filesystem, validation, and logging helpers for WebOpti."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError


def setup_logging(log_file: Path) -> logging.Logger:
    """Configure the application log once and return the WebOpti logger."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logging.getLogger("webopti")


def validate_image(path: Path) -> tuple[bool, str, tuple[int, int] | None]:
    """Check that an image is readable and has a non-zero canvas."""
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            if width < 1 or height < 1:
                return False, "image has invalid dimensions", None
            return True, "", (width, height)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        return False, str(error) or error.__class__.__name__, None
