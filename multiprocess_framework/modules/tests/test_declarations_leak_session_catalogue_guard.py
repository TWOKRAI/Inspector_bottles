# -*- coding: utf-8 -*-
"""RED (Task 0.1, критерий 3) — страж сетки: каталог метрик фреймворка на закрытии сессии.

Независимый приёмочный тест, написанный ДО реализации. Источник — Acceptance criteria
задачи 0.1: «Каталог метрик фреймворка после полного прогона сессии совпадает с
литералом ``('cycle_duration_ms', 'effective_hz', 'fps', 'latency_ms', 'shm')`` —
утечка объявления из любого будущего теста должна краснеть ПОИМЁННО».

**Почему фикстура, а не голый вызов в теле теста.** Свойство — про КОНЕЦ ВСЕЙ
сессии pytest, а не про момент, когда исполняется именно этот файл (порядок
сборки директорий в общем прогоне произволен). ``scope="session", autouse=True``
именно так и устроен в pytest: teardown session-scoped фикстуры откладывается до
самого конца прогона (после последнего теста, где бы он ни лежал), НЕ до конца
локального каталога — ровно то поведение, которое нужно стражу.

**Демонстрация красноты (проверено вручную 2026-08-28).** Пять метрик объявляются
при ИМПОРТЕ `process_module/heartbeat/telemetry.py` и `process_heartbeat.py`.
Прогон `pytest multiprocess_framework/modules/tests multiprocess_framework/modules/
statistics_module/tests multiprocess_framework/modules/process_module/tests` (в
таком порядке, что заставляет голый `forget_declarations()` сработать РАНЬШЕ
`process_module/tests`) даёт на закрытии сессии каталог ``()`` вместо ожидаемых
пяти имён — потому что производители уже импортированы и стёртое им объявить
заново некому. Страж обязан назвать это по имени, а не молча пропустить.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.observability_declarations import declared_metrics

#: Пять метрик, которые объявляет фреймворк (Task 0.1, Acceptance §3) — литерал
#: из спеки задачи, а не значение, вычисленное тем же кодом, что проверяется.
_EXPECTED_FRAMEWORK_METRICS = ("cycle_duration_ms", "effective_hz", "fps", "latency_ms", "shm")


@pytest.fixture(scope="session", autouse=True)
def _framework_metric_catalogue_guard_at_session_close() -> None:
    """Снимает каталог метрик РОВНО ОДИН РАЗ, в teardown, после последнего теста сессии."""
    yield
    catalogue = declared_metrics()
    expected = set(_EXPECTED_FRAMEWORK_METRICS)
    actual = set(catalogue)
    assert catalogue == _EXPECTED_FRAMEWORK_METRICS, (
        "каталог метрик фреймворка на закрытии сессии разошёлся с ожидаемым литералом "
        f"{_EXPECTED_FRAMEWORK_METRICS!r}: получили {catalogue!r}. "
        f"лишние={sorted(actual - expected)!r}, пропавшие={sorted(expected - actual)!r} — "
        "утечка объявления из какого-то теста в этой сессии названа поимённо выше."
    )


def test_session_guard_fixture_is_wired_into_this_session() -> None:
    """Пусковой тест: одного его наличия хватает, чтобы фикстура выше подключилась
    к сессии — сама проверка (см. докстроку фикстуры) идёт в её teardown.
    """
    assert True
