"""Structured logging configuration for Neural Extractor."""

import logging
import sys
from pathlib import Path

from neural_extractor.config import get_data_dir

# Create logs directory if it doesn't exist
LOGS_DIR = get_data_dir() / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOGS_DIR / "neural_extractor.log"


def setup_logger(
    name: str = "neural_extractor",
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> logging.Logger:
    """
    Set up a structured logger for Neural Extractor.

    Args:
        name: Logger name
        level: Logging level (default: INFO)
        log_file: Optional log file path (default: logs/neural_extractor.log)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = LOG_FILE

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# Default logger instance
logger = setup_logger()
