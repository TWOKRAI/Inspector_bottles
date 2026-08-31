# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): windowed_suppressed в readback.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «Счётчик windowed_suppressed виден в readback наблюдаемости (там же, где
    остальные счётчики плоскостей). Событие подавлено → счётчик вырос.
    Отдельно нужен тест на класс дефекта «событие есть, а счётчик 0».»

Место «readback наблюдаемости, где остальные счётчики плоскостей» — не
угадано, а найдено чтением: ``observability_reload.PLANE_COUNTER_KEYS`` — это
ИМЕННО тот жёсткий whitelist, который решает, какие ключи из
``manager.get_stats()`` уезжают наружу в ``introspect.observability``
(докстринг над кортежем прямо называет класс дефекта «счётчик посчитан, но не
опубликован» и ссылается на живой прецедент Ф0.3). Рядом уже стоит
``records_sampled_out`` — счётчик того же типа (дроссель Ф7.1) — как пример
формы записи.

Часть А — статическая (страж уровня «объявлен ли ключ» — самая дешёвая и
самая прямая проверка критерия «виден в readback»). Часть Б —
«событие есть, счётчик 0» как класс дефекта: специально пишу его как ОТДЕЛЬНЫЙ
тест, а не довесок к части А, ровно как просит критерий, и **сознательно
делаю его сегодня нерабочим** (skip с объяснением), потому что без реального
менеджера, владеющего ``log_windowed``, воспроизвести «событие есть» нечем —
сам примитив ещё не существует (см. companion-тест
``channel_routing_module/tests/test_windowed_voice_primitive_acceptance.py``).
Оставляю тест здесь как ЗАЯВЛЕННОЕ намерение (имя + докстринг), а не выдаю
skip за прошедшую проверку.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.managers.observability_reload import (
    PLANE_COUNTER_KEYS,
)


class TestWindowedSuppressedIsPublished:
    def test_windowed_suppressed_key_is_in_the_publish_whitelist(self) -> None:
        assert "windowed_suppressed" in PLANE_COUNTER_KEYS, (
            "'windowed_suppressed' обязан быть в PLANE_COUNTER_KEYS — иначе живой "
            "get_stats() менеджера может считать счётчик правильно, а наружу в "
            "introspect.observability он не поедет (класс дефекта Ф0.3, названный "
            "в докстринге самого whitelist'а)"
        )


class TestZeroCounterWithAnEventIsADistinctDefectClass:
    """Часть Б — «событие есть, счётчик 0» отдельно от простого наличия ключа.

    Честно: этот тест не могу довести до реального RED без выбора конкретного
    менеджера-владельца ``log_windowed`` (примитив ещё не существует нигде —
    сверено grep'ом по всему дереву). Skip — не «прошла проверка», а
    «заявленное намерение», и я называю это прямо, а не маскирую тишиной.
    """

    @pytest.mark.skip(
        reason=(
            "требует реального владельца log_windowed (LoggerManager/ErrorManager/"
            "StatsManager?) — примитив ещё не реализован нигде в дереве; заявленное "
            "намерение, не пройденная проверка. См. докстринг класса."
        )
    )
    def test_a_suppressed_voice_increments_windowed_suppressed_not_zero(self) -> None:
        raise NotImplementedError(
            "дозаполнить, когда будет известен реальный владелец log_windowed: "
            "вызвать log_windowed дважды с одним key внутри окна, прочитать "
            "владельца.get_stats()['windowed_suppressed'] и убедиться, что он == 1, "
            "а не 0 при том, что подавление реально произошло"
        )
