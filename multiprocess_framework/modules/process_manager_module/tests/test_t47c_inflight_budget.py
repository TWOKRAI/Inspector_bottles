# -*- coding: utf-8 -*-
"""Task 4.7c — слепые приёмочные тесты `inflight_budget` (RED до реализации).

Контракт (plans/transport-single-policy/task-4.7.md, раздел 4.7c):
``inflight_budget(writer_depths, *, queue=None, lag=None, process="?") -> (data_queue_maxsize,
chain_max_lag_items)``. D = min(writer_depths); бюджет в полёте B = D - 2. По умолчанию lag = 2,
queue = B - lag. D < 4 -> ValueError.

Переделка по вердикту CTO (C2/C3): первый элемент результата — НЕ maxsize IPC-очереди, а транзитный
запас B - lag (его измеряет приёмник). Явный ``queue`` — это cap рецепта: возвращается как задан,
БЕЗ ошибки «очередь больше кольца» (старая модель ошибалась при queue + lag > B).

Ожидаемые значения — литералы, не пересчёт формулой из тестируемого кода.
Импорт новой функции — ленивый, внутри каждого теста: отсутствие модуля роняет каждый тест
по отдельности (ImportError), а не весь файл на сборе.
"""

from __future__ import annotations

import pytest


def _budget(*args, **kwargs):
    from multiprocess_framework.modules.process_manager_module.topology.inflight import inflight_budget

    return inflight_budget(*args, **kwargs)


def test_depth8_gives_4_2():
    """Кольцо 8 -> бюджет 6 -> очередь 4 + lag 2."""
    assert _budget([8]) == (4, 2)


def test_depth12_gives_8_2_and_min_of_writers():
    """Кольцо 12 -> очередь 8, lag 2; два писателя 8 и 12 -> считается по минимуму (4, 2)."""
    assert _budget([12]) == (8, 2)
    assert _budget([8, 12]) == (4, 2)
    assert _budget([12, 8]) == (4, 2)  # порядок писателей не влияет


def test_explicit_queue_20_depth_8_kept_as_cap_no_error():
    """Явная очередь 20 при кольце 8 -> возвращается как задана вместе с lag по умолчанию: (20, 2).
    Старая модель бросала ValueError «очередь 20 больше кольца 8»; теперь очередь — cap памяти."""
    assert _budget([8], queue=20, process="detector_7") == (20, 2)


def test_depth_below_4_error():
    """D = 3 -> ValueError: на очередь >= 1 и lag >= 1 места нет (lag 0 = «без границы»)."""
    with pytest.raises(ValueError):
        _budget([3])


def test_depth_below_4_among_writers_error():
    """Один тонкий писатель среди глубоких тянет всё вниз: [12, 3] -> ValueError (D = min = 3)."""
    with pytest.raises(ValueError):
        _budget([12, 3])


def test_depth_exactly_4_gives_1_1():
    """Граница D = 4: B = 2, единственное разбиение с queue >= 1 и lag >= 1 — (1, 1).

    Спека говорит «lag по умолчанию 2», но при B = 2 это дало бы очередь 0 — поэтому на границе
    ждём (1, 1), а не ValueError (D < 4 — ошибка, D = 4 — уже нет) и не lag 0.
    """
    assert _budget([4]) == (1, 1)


def test_depth_5_gives_1_2():
    """D = 5: B = 3 -> очередь 1, lag 2 (первый D, где работает lag = 2 по умолчанию)."""
    assert _budget([5]) == (1, 2)


@pytest.mark.parametrize(
    ("queue", "expected"),
    [
        (4, (4, 2)),  # ровно на границе бюджета: 4 + 2 = 6 = D - 2
        (2, (2, 2)),  # ниже границы — принимается как есть, бюджет не обязан быть выбран целиком
    ],
)
def test_explicit_queue_within_budget_is_kept(queue, expected):
    """Явная очередь в пределах бюджета (с lag по умолчанию 2) возвращается как задана."""
    assert _budget([8], queue=queue) == expected


def test_explicit_queue_5_depth_8_kept_as_cap_no_error():
    """Граница, на которой старая модель отвергала (5 + lag 2 = 7 > B = 6): теперь (5, 2) без ошибки."""
    assert _budget([8], queue=5, process="p") == (5, 2)


def test_explicit_lag_3_gives_queue_3():
    """Явный lag 3 при кольце 8: очередь добирается до остатка бюджета — 6 - 3 = 3."""
    assert _budget([8], lag=3) == (3, 3)


@pytest.mark.parametrize("depth", list(range(4, 17)))
def test_default_budget_never_zero_and_fits_in_ring(depth):
    """Для любого D >= 4 по умолчанию: очередь >= 1, lag >= 1 (lag 0 = «без границы», ловушка),
    очередь + lag не выходит за D - 2, lag не больше 2."""
    queue, lag = _budget([depth])
    assert queue >= 1
    assert lag >= 1
    assert queue + lag <= depth - 2
    assert lag <= 2
