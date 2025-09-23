"""
Logger configuration module.
"""

import sys
from loguru import logger
from app.core.settings import settings

LOG_FORMAT = " ".join(
    [
        "<level>{level: <8}</level>",
        "<cyan>{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan>",
        "[<blue>Process {process}</blue>|<yellow>Thread {thread}</yellow>]",
        "<magenta>{name}</magenta>:<cyan>{function}</cyan>:<red>{line}</red>",
        "- <level>{message}</level>",
    ]
)


def _setup_logger():
    """
    Cleans and sets up the logger with the specified configuration.
    """
    new_logger = logger.bind()
    new_logger.remove()
    new_logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        colorize=settings.DEBUG,
        level="DEBUG" if settings.DEBUG else "INFO",
        backtrace=True,
        diagnose=True,
    )

    return new_logger


# Global logger instance
log = _setup_logger()
