"""Динамическая загрузка класса процесса + лёгкий логгер до LoggerManager."""

import importlib
import traceback
from typing import Any, Optional, Type


class _ProcessLogger:
    """Лёгкий логгер: LoggerManager если доступен, иначе print."""

    def __init__(self, process_name: str, logger_manager=None):
        self._name = process_name
        self._lm = logger_manager

    def info(self, msg: str) -> None:
        if self._lm:
            self._lm.info(msg, module=self._name)
        else:
            print(f"[{self._name}] {msg}", flush=True)

    def warning(self, msg: str) -> None:
        if self._lm:
            self._lm.warning(msg, module=self._name)
        else:
            print(f"[{self._name}] WARNING: {msg}", flush=True)

    def error(self, msg: str) -> None:
        if self._lm:
            self._lm.error(msg, module=self._name)
        else:
            print(f"[{self._name}] ERROR: {msg}", flush=True)


def _load_process_class(class_path: str, log: _ProcessLogger) -> Optional[Type[Any]]:
    """Загрузить класс процесса по полному пути модуля."""
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as e:
        log.error(f"Failed to load process class '{class_path}': {e}")
        traceback.print_exc()
        return None
