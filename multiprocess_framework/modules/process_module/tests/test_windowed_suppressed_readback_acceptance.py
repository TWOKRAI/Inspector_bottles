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
тест, а не довесок к части А, ровно как просит критерий.

**Часть Б ЗАПОЛНЕНА после реализации (ревью Task 1.4, блокер 1).** Тестер
оставил её ``skip``'ом с честной оговоркой «нужен реальный владелец
``log_windowed``» — владельца тогда не существовало. Ревью воспроизвело, чем
обошёлся незаполненный skip: заплатка ``base_stats.update(voice_counters())``
→ ``pass`` в ``logger_core.py`` не роняла НИ ОДНОГО теста из 350. Часть А
проверяет ЧЛЕНСТВО ключа в белом списке, сторож автора читает
``voice_counters()`` напрямую — мимо менеджера, — и между «величина посчитана»
и «величина видна в readback» не стояло ничего, хотя в критерии написано
именно «в readback».

Владелец здесь — НАСТОЯЩИЙ ``LoggerManager`` (не фейк и не заглушка): фейковый
харнесс доказал бы харнесс, а спрашивается дорога
``take() → _bump → voice_counters() → LoggerCore.get_stats()``, у которой все
четыре звена боевые.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.windowed_voice import reset_voice_counters
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    PLANE_COUNTER_KEYS,
)


@contextmanager
def _real_logger(tmp_path: Path) -> Iterator[LoggerManager]:
    """Боевой ``LoggerManager`` с одним файловым приёмником.

    Именно менеджер, а не ``WindowedVoices`` и не мок: спрашивается публикация
    в ``get_stats()``, а её делает ``LoggerCore``.
    """
    config = LoggerManagerConfig(
        app_name="windowed_readback",
        log_directory=str(tmp_path),
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            )
        },
        default_level="DEBUG",
        scopes={scope: LoggerScopeSchema(channels=["system_file"]) for scope in ("SYSTEM", "BUSINESS", "DEBUG")},
    )
    manager = LoggerManager(manager_name="WindowedReadbackLogger", config=config)
    try:
        yield manager
    finally:
        manager.shutdown()


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

    Заполнено по блокеру 1 ревью Task 1.4. Дорога проверяется целиком и с
    боевого конца: голос подавлен у настоящего менеджера → величина обязана
    быть видна в ЕГО ``get_stats()``. Снятие публикации в ``logger_core.py``
    роняет оба теста класса ``KeyError``'ом, снятие ``_bump`` — первый.
    """

    @pytest.fixture(autouse=True)
    def _clean_process_counters(self) -> Iterator[None]:
        # Счётчики ПРОЦЕССНЫЕ (см. докстринг ``voice_counters``): без обнуления
        # тест читал бы сумму со всем, что успело подавиться в этой же сессии
        # pytest, и литерал перестал бы быть литералом.
        reset_voice_counters()
        yield
        reset_voice_counters()

    def test_a_suppressed_voice_increments_windowed_suppressed_not_zero(self, tmp_path: Path) -> None:
        with _real_logger(tmp_path) as manager:
            for _ in range(5):
                manager.log_windowed("readback:probe", 60.0, "warning", message="повторяющееся состояние процесса")
            stats = manager.get_stats()

        assert "windowed_suppressed" in stats, (
            "величина не доехала до readback менеджера: посчитать её мало, "
            f"спросить у живого процесса нечем. Ключи get_stats(): {sorted(stats)}"
        )
        # 4 — литерал: пять вызовов в окне 60 с, первый голосит, четыре подавлены.
        # Вывести это число из механизма значило бы согласиться с любым ответом,
        # включая 0 — ровно тот класс дефекта, о котором просит критерий.
        assert stats["windowed_suppressed"] == 4, (
            f"событие есть, а счётчик в readback показывает {stats['windowed_suppressed']} вместо 4"
        )

    def test_without_suppression_the_published_counter_stays_zero(self, tmp_path: Path) -> None:
        """Контроль: без подавления величина в readback обязана быть нулём.

        Без этой половины предыдущий тест проходил бы и у счётчика, который
        растёт на КАЖДЫЙ голос, — то есть перестал бы означать «подавлено».
        Ключ при этом обязан ПРИСУТСТВОВАТЬ: «ключа нет» и «потерь нет» —
        разные факты (правило присутствия ключей нулями, Ф0.4).
        """
        with _real_logger(tmp_path) as manager:
            for i in range(5):
                manager.log_windowed(f"readback:probe:{i}", 60.0, "warning", message="разные ключи")
            stats = manager.get_stats()

        assert stats["windowed_suppressed"] == 0, (
            f"пять РАЗНЫХ ключей голосят каждый, подавлений нет: {stats['windowed_suppressed']}"
        )
        assert stats["windowed_keys_evicted"] == 0, (
            f"пять ключей — не потолок карты, выбрасывать было нечего: {stats['windowed_keys_evicted']}"
        )
