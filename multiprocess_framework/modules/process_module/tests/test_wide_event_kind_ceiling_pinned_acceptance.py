# -*- coding: utf-8 -*-
"""Независимая приёмка Ф6 — Предмет 3: потолок числа родов события
(``WideEventSelector.KIND_CEILING``) обязан быть пришпилен ЛИТЕРАЛОМ, а не
выводиться из той же константы, которую он охраняет.

Измерено ревью (см. промпт задания): единственный существующий сторож
(``test_wide_event_hazards.py``, ``assert len(counters) == WideEventSelector.KIND_CEILING + 1``)
выводит ожидание ИЗ ТОЙ ЖЕ константы — правка ``64 -> 4`` там даёт 140 passed
и ноль красных, потому что тест соглашается с ЛЮБЫМ значением ``KIND_CEILING``.

D7 добавляет якорь ОТДЕЛЬНОЙ строкой (``== 64``, литерал) и рядом —
поведенческую проверку самой границы, тоже литералом 64/65, не через
константу: без якоря поведенческий тест сам по себе так же бессилен, как и
прежний сторож.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    WideEventSelector,
)


class TestD7_KindCeilingIsPinnedAsALiteralNotDerivedFromItself:
    def test_kind_ceiling_constant_is_exactly_64(self) -> None:
        """Якорь: без него поведенческий тест ниже пользуется константой и
        соглашается с любым её значением — ровно дефект, найденный ревью."""
        assert WideEventSelector.KIND_CEILING == 64

    def test_the_65th_distinct_kind_is_the_first_to_collapse_into_the_overflow_bucket(self) -> None:
        """Граница проверяется литералами 64/65, НЕ через ``KIND_CEILING`` —
        иначе эта проверка страдала бы тем же дефектом, что и старый сторож."""
        selector = WideEventSelector(first_n=1, every_mth=0)
        for i in range(64):
            selector.select(f"kind_{i}")

        counters_at_64 = selector.counters()
        assert len(counters_at_64) == 64, "первые 64 РАЗНЫХ рода обязаны получить каждый свой собственный бакет"
        assert selector.kinds_saturated == 0, "потолок не достигнут — насыщения быть не должно"

        selector.select("kind_64")  # 65-й отличный род — первый, кто переполняет

        counters_after = selector.counters()
        assert len(counters_after) == 65, (
            "65-й род не заводит новый бакет: 64 старых + 1 общий OVERFLOW = 65 записей readback'а"
        )
        assert WideEventSelector.OVERFLOW_KIND in counters_after, "переполнение обязано лечь в ИМЕНОВАННЫЙ общий бакет"
        assert selector.kinds_saturated == 1, "ровно один род ушёл в переполнение на этом шаге"
