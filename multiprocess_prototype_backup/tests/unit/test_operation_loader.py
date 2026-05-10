"""Unit-тесты для load_operation_class и clear_cache (Phase 5a)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# load_operation_class использует importlib с короткими путями
# (services.processor.operations.color_detection_op.ColorDetectionOp)
# Добавляем multiprocess_prototype/ в sys.path чтобы короткие пути резолвились
_V3_ROOT = Path(__file__).resolve().parents[2]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype.services.processor.operations.loader import (  # noqa: E402
    clear_cache,
    load_operation_class,
)


# Убеждаемся, что кэш чист перед началом тестов
@pytest.fixture(autouse=True)
def reset_cache():
    """Сбросить кэш загрузчика перед каждым тестом."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Тесты загрузки реальных операций
# ---------------------------------------------------------------------------


def test_load_color_detection_op_returns_class():
    """Загрузка ColorDetectionOp по полному dotted-пути возвращает класс."""
    cls = load_operation_class(
        "services.processor.operations.color_detection_op.ColorDetectionOp"
    )
    assert cls is not None
    # Убеждаемся что это класс (а не экземпляр)
    assert isinstance(cls, type)


def test_load_color_detection_op_class_name():
    """Загруженный класс должен называться ColorDetectionOp."""
    cls = load_operation_class(
        "services.processor.operations.color_detection_op.ColorDetectionOp"
    )
    assert cls.__name__ == "ColorDetectionOp"


def test_load_blob_detection_op_returns_class():
    """Загрузка BlobDetectionOp по полному dotted-пути возвращает класс."""
    cls = load_operation_class(
        "services.processor.operations.blob_detection_op.BlobDetectionOp"
    )
    assert cls is not None
    assert isinstance(cls, type)


def test_load_blob_detection_op_class_name():
    """Загруженный класс должен называться BlobDetectionOp."""
    cls = load_operation_class(
        "services.processor.operations.blob_detection_op.BlobDetectionOp"
    )
    assert cls.__name__ == "BlobDetectionOp"


# ---------------------------------------------------------------------------
# Тесты ошибок
# ---------------------------------------------------------------------------


def test_load_nonexistent_module_raises_import_error():
    """Несуществующий модуль → ImportError."""
    with pytest.raises(ImportError):
        load_operation_class("services.nonexistent.module.SomeClass")


def test_load_nonexistent_class_in_valid_module_raises_import_error():
    """Существующий модуль, но несуществующий класс → ImportError."""
    with pytest.raises(ImportError):
        load_operation_class(
            "services.processor.operations.color_detection_op.NonExistentClass"
        )


def test_load_path_without_dot_raises_import_error():
    """Путь без точки (некорректный formаt) → ImportError."""
    with pytest.raises(ImportError):
        load_operation_class("NoDotsHere")


# ---------------------------------------------------------------------------
# Тесты кэша
# ---------------------------------------------------------------------------


def test_cache_same_path_returns_same_object():
    """Повторный вызов с тем же module_path → тот же объект класса (is-check)."""
    path = "services.processor.operations.color_detection_op.ColorDetectionOp"
    cls1 = load_operation_class(path)
    cls2 = load_operation_class(path)
    assert cls1 is cls2


def test_clear_cache_allows_reload():
    """После clear_cache загрузка снова работает (кэш не ломает логику)."""
    path = "services.processor.operations.blob_detection_op.BlobDetectionOp"

    cls1 = load_operation_class(path)
    clear_cache()
    cls2 = load_operation_class(path)

    # Оба вызова должны вернуть правильный класс
    assert cls2.__name__ == "BlobDetectionOp"
    # После clear_cache объект может быть тем же (тот же модуль в памяти),
    # но сам факт повторной загрузки не должен бросать исключений
    assert cls1.__name__ == cls2.__name__
