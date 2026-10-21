"""Headless component feedback; terminal applications may inject UI callbacks."""

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def show_progress(message):
    """Report an operation through application logging without owning a UI."""
    logger.info("%s", message)
    yield


def show_success(message):
    """Report completion through application logging."""
    logger.info("%s", message)
