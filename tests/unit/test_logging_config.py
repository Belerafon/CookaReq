"""Tests for logging config."""

import logging

import pytest

from app.log import configure_logging, logger

pytestmark = pytest.mark.unit


@pytest.fixture
def reset_logger() -> None:
    prev_handlers = list(logger.handlers)
    prev_level = logger.level
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    try:
        yield
    finally:
        logger.handlers.clear()
        logger.handlers.extend(prev_handlers)
        logger.setLevel(prev_level)


def test_configure_logging_adds_handler_once(reset_logger: None) -> None:
    configure_logging()
    assert len(logger.handlers) == 1
    first_handler = logger.handlers[0]
    configure_logging()
    assert len(logger.handlers) == 1
    assert logger.handlers[0] is first_handler


def test_configure_logging_sets_level(reset_logger: None) -> None:
    configure_logging(level=logging.DEBUG)
    assert logger.level == logging.DEBUG
    configure_logging(level=logging.WARNING)
    assert logger.level == logging.DEBUG
