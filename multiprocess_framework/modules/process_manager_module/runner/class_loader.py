"""Динамическая загрузка класса процесса + лёгкий логгер до LoggerManager."""

import importlib
import traceback
from typing import Any, Optional, Type

from ...logger_module.utils import FallbackLogger


class _ProcessLogger:
    """Лёгкий логгер: LoggerManager если доступен, иначе fallback.

    Ф2.1: fallback теперь именован процессом, а не этим модулем. Раньше ветка
    без явного ``logger_manager`` уходила в общий ``_logger`` файла, и имя
    процесса оставалось только в ТЕКСТЕ сообщения — поле источника у стартовых
    строк всех процессов было одинаковым. ``process_runner`` создаёт логгер
    именно без менеджера (``_ProcessLogger(process_name)``), то есть на живом
    прогоне работала ровно эта ветка.

    Текст уходит аргументом (``"%s", msg``), а не шаблоном: сообщение приходит
    от вызывающего кода и может содержать ``%``.
    """

    def __init__(self, process_name: str, logger_manager=None):
        self._name = process_name
        self._lm = logger_manager
        self._fallback = FallbackLogger(process_name)

    def info(self, msg: str) -> None:
        if self._lm:
            self._lm.info(msg, module=self._name)
        else:
            self._fallback.info("%s", msg)

    def warning(self, msg: str) -> None:
        if self._lm:
            self._lm.warning(msg, module=self._name)
        else:
            self._fallback.warning("%s", msg)

    def error(self, msg: str) -> None:
        if self._lm:
            self._lm.error(msg, module=self._name)
        else:
            self._fallback.error("%s", msg)


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
