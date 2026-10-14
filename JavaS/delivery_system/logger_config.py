"""Настройка логирования: файл logs/delivery.log с ротацией + (опционально) консоль."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO, log_dir=None, console: bool = False) -> logging.Logger:
    """Настраивает корневой логгер приложения 'delivery' и возвращает его."""
    log_dir = Path(log_dir or LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("delivery")
    logger.setLevel(level)
    for handler in list(logger.handlers):  # повторный вызов не дублирует обработчики
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = RotatingFileHandler(log_dir / "delivery.log", maxBytes=1_000_000,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setLevel(logging.DEBUG if level <= logging.DEBUG else logging.WARNING)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    logger.propagate = False
    return logger
