"""Pytest: PYTHONPATH к каталогу modules + корень проекта, снимок реестра объявлений, возврат заморозки gc."""

import gc
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def freeze_restored():
    """Блок, после которого заморозка gc возвращена к той, что была до него.

    Зачем: тесты механизма заморозки (и выход ``suspend_collection_owner``, когда сессионный
    владелец морозил) зовут ``gc.unfreeze()``. Он глобален: все permanent-объекты процесса
    pytest (сессионная заморозка границы, сотни тысяч объектов) уходят в старшее поколение, и
    следующая граница теста обходит всю кучу — пауза 170–280 мс на тест.

    Выборочно разморозить нельзя, поэтому на выходе, если ``gc.get_freeze_count()`` изменился:
    ``gc.unfreeze()`` → ``gc.collect(1)`` (только молодые поколения: мусор блока не уходит в
    permanent, полной сборки нет) → ``gc.freeze()`` при ``n0 > 0``. ``n0 == 0`` (файл гоняют
    одиночно, сессионной заморозки нет) — прежнее поведение: только ``gc.unfreeze()``.
    Мусор, который блок сам успел заморозить, ``collect(1)`` не достаёт (он в старшем поколении).
    """
    n0 = gc.get_freeze_count()
    try:
        yield
    finally:
        if gc.get_freeze_count() != n0:
            gc.unfreeze()
            gc.collect(1)
            if n0 > 0:
                gc.freeze()


_modules = Path(__file__).resolve().parent.parent.parent
_root = _modules.parent.parent
for p in (_modules, _root):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

import pytest  # noqa: E402

from multiprocess_framework.modules.observability_declarations import (  # noqa: E402
    restore,
    snapshot,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (  # noqa: E402
    ensure_framework_producers,
)


@pytest.fixture(autouse=True)
def declarations_snapshot():
    """Снимок реестра объявлений до теста, возврат к нему после.

    Близнец фикстуры из ``statistics_module/tests/conftest.py`` — полное
    обоснование там же (Ф0.1 «trust gate»). Кратко: реестр процессный и
    наполняется импортом, поэтому след теста в нём достаётся соседям, а не
    автору; снимок/возврат ограничивает след самим тестом.

    ``ensure_framework_producers()`` зовётся ДО снимка намеренно: ``restore``
    возвращает реестр к снимку и стирает в том числе объявления, сделанные
    ИМПОРТОМ во время теста, — а такое объявление обратно не вернётся (модуль
    уже в ``sys.modules``). Догрев кладёт пятёрку метрик фреймворка внутрь
    снимка, и терять её нечему. Здесь это к тому же почти всегда no-op:
    ``heartbeat`` в этом пакете импортируют тесты на верхнем уровне файлов.
    """
    ensure_framework_producers()
    state = snapshot()
    yield
    restore(state)


@pytest.fixture
def gc_freeze_restored():
    """Тест (и фикстуры, зависящие от этой) внутри ``freeze_restored()`` — см. его docstring.

    Фикстуры со ``suspend_collection_owner`` зависят от этой: выход suspend сам зовёт
    ``gc.unfreeze()`` (``_rearm`` морозившего владельца), и восстановление должно идти ПОСЛЕ него.
    """
    with freeze_restored():
        yield


@pytest.fixture
def freeze_restore_block():
    """Сам контекст-менеджер ``freeze_restored`` — для тестов на него (без импорта conftest)."""
    return freeze_restored
