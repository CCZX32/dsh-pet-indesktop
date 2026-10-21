from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "petcore"
_configured = False


def setup_logging(log_dir: Path, *, verbose: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "petcore.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        handler = None
    if handler is not None:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _configured = True
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)
