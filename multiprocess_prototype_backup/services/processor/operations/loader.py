"""Динамический загрузчик классов операций по module_path."""

from __future__ import annotations

import functools
import importlib


@functools.lru_cache(maxsize=None)
def load_operation_class(module_path: str) -> type:
    """Загрузить класс операции по dotted module_path.

    Последний сегмент пути — имя класса, всё остальное — путь к модулю.
    Пример: 'services.processor.operations.color_detection_op.ColorDetectionOp'
      → import services.processor.operations.color_detection_op
      → getattr ColorDetectionOp

    Результат кэшируется через lru_cache для повторных вызовов.

    Args:
        module_path: Полный dotted path до класса операции.

    Returns:
        Класс операции.

    Raises:
        ImportError: Если модуль не найден или класс отсутствует в модуле.
    """
    if "." not in module_path:
        raise ImportError(
            f"Некорректный module_path '{module_path}': "
            "ожидается полный dotted path вида 'package.module.ClassName'."
        )

    # Разбиваем путь на модуль и имя класса
    module_dotted, class_name = module_path.rsplit(".", maxsplit=1)

    # Импортируем модуль
    try:
        module = importlib.import_module(module_dotted)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Модуль '{module_dotted}' не найден (из module_path='{module_path}')."
        ) from exc

    # Получаем класс из модуля
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(
            f"Класс '{class_name}' не найден в модуле '{module_dotted}' "
            f"(module_path='{module_path}')."
        )

    return cls


def clear_cache() -> None:
    """Сбросить кэш загрузчика. Используется в тестах."""
    load_operation_class.cache_clear()
