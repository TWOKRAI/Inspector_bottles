"""Pytest: PYTHONPATH к каталогу modules + корень проекта, снимок реестра объявлений, изоляция тестов механизма gc.

Тесты механизма заморозки gc (``collect_ignore`` ниже) зовут настоящие ``gc.freeze``/``gc.unfreeze``
и ``suspend_collection_owner``. Это глобальное состояние процесса: в общем прогоне они размораживали
бы сессионную кучу pytest, и вернуть её точно нельзя (``gc.get_freeze_count()`` не монотонен).
Поэтому эти файлы здесь не собираются, а идут в своём интерпретаторе через
``test_gc_mechanism_own_interpreter.py``. Спек: plans/2026-10-03_lifecycle-owner-scope/task-T1-gc-isolation.md.
"""

import sys
from pathlib import Path

#: Файлы, которые общий прогон не собирает: их гоняет дочерний интерпретатор.
#: Единственный источник списка (литерал: его читает AST-страж R4 в tests/test_gc_policy_guard.py).
collect_ignore = ["test_gc_collection_owner.py", "test_gc_discipline.py"]

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
def own_interpreter_files() -> list[Path]:
    """Абсолютные пути файлов из ``collect_ignore`` — их запускает дочерний интерпретатор."""
    here = Path(__file__).resolve().parent
    return [here / name for name in collect_ignore]
