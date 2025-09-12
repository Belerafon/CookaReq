import logging

logger = logging.getLogger("cookareq")

def configure_logging(level: int = logging.INFO) -> None:
    """Configure application logger once."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)

