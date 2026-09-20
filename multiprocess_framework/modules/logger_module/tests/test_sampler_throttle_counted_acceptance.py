# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester): дроссель сэмплера считается.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «Дроссель сэмплера считается. При включённом sampling_first_n подавленные
    записи дают records_sampled_out > 0.»

**Находка, а не провал.** По чтению кода этот механизм уже существует и
покрыт тестами СЕГОДНЯ, ДО начала задачи «окна голосов»:
``logger_module/core/sampling.py`` (``records_sampled_out`` считается на
каждое подавление), уже выставлен в ``LoggerCore.get_stats()`` (строка ~1980)
и уже опубликован в ``observability_reload.PLANE_COUNTER_KEYS``. Секция
``sampling_first_n`` в ``ObservabilityConfig`` датирована Ф7.1 — это отдельный,
более ранний механизм («дроссель повторяющихся записей по тексту»), а не
часть задачи «окна голосов» (``log_windowed`` per-key, число подавленных В
ТЕКСТЕ следующего голоса). Два механизма родственные (оба — троттлинг), но
разные: этот работает по ключу «уровень+текст» с first-N/every-Mth, новый —
по явному ``key`` с постоянным окном.

Пишу тест независимо (не копирую существующий
``test_sampling_contract.py::TestStatsVisibility``, хоть и беру ту же схему
конструирования ``LoggerCore`` — она стандартна для модуля, см. «искать
существующие тесты, следовать их стилю») и ОЖИДАЮ его зелёным уже сегодня.
Если он покраснеет — это будет означать, что я ошибся в модели (либо
существующий механизм отличается от того, что я вычитал), и это нужно
разобрать отдельно, а не списать на «ещё не реализовано».
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.log_types import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore


class _SpyChannel(IChannel):
    def __init__(self, name: str) -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _logger_with_sampling(**sampling_kwargs: Any) -> LoggerCore:
    config: Dict[str, Any] = {
        "app_name": "sampler_throttle_counted",
        "enable_batching": False,
        "modules": {},
        "channels": {},
        "default_level": "DEBUG",
        "scopes": {"SYSTEM": {"channels": ["a"]}},
    }
    config.update(sampling_kwargs)
    mgr = LoggerCore(manager_name="SamplerThrottleCountedLogger", config=config)
    mgr.initialize()
    return mgr


class TestSamplerThrottleIsCounted:
    def test_suppressed_records_make_records_sampled_out_positive(self) -> None:
        mgr = _logger_with_sampling(sampling_first_n=1, sampling_every_mth=1_000_000)
        spy = _SpyChannel("a")
        mgr.register_channel(spy)

        # Первая — проходит (first_n=1); вторая — идентичная, подавляется.
        mgr.log("SYSTEM", LogLevel.DEBUG, "повторяющийся текст", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повторяющийся текст", "mod")

        stats = mgr.get_stats()
        assert stats.get("records_sampled_out", 0) > 0, (
            f"после гарантированного подавления второй идентичной записи "
            f"records_sampled_out обязан быть > 0, получено {stats.get('records_sampled_out')!r}"
        )
        mgr.shutdown()

    def test_without_suppression_the_counter_stays_zero(self) -> None:
        """Отрицательный контроль: без подавлений счётчик — 0, не отсутствует."""
        mgr = _logger_with_sampling(sampling_first_n=0)
        spy = _SpyChannel("a")
        mgr.register_channel(spy)

        mgr.log("SYSTEM", LogLevel.DEBUG, "без дросселя", "mod")

        stats = mgr.get_stats()
        assert stats.get("records_sampled_out", None) == 0, (
            f"без подавлений счётчик обязан быть 0 (а не отсутствовать), получено {stats.get('records_sampled_out')!r}"
        )
        mgr.shutdown()
