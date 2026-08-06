# -*- coding: utf-8 -*-
"""Контрактные тесты дросселя повторяющихся записей (Ф7.1).

НЕЗАВИСИМЫЙ тестировщик: написаны СТРОГО по объявленному контракту
(``LoggerManagerConfig.sampling_*`` + текстовые критерии приёмки), без
чтения ``logger_module/core/sampling.py``. Источник истины — сигнатуры
``LoggerCore.log()`` / ``get_stats()`` и поля конфига, не реализация.

Формула «после первых N проходит каждая M-я одинаковая» в этих тестах
прочитана как: считать occurrence-индекс ЗАПИСИ ключа (уровень+текст)
начиная с 1; первые ``sampling_first_n`` проходят всегда; для записей
ПОСЛЕ порога считается ОТНОСИТЕЛЬНЫЙ индекс (1, 2, 3, ...), и проходит
та, чей относительный индекс кратен ``sampling_every_mth`` (аналог
классического «первые N плюс 1 из M» — как в zap/logging-сэмплерах).
Если реализация считает иначе — тест 3 и тест 8 упадут с конкретным
числом, и это отдельная находка, а не повод молча подогнать литерал.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.log_types import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore


class _SpyChannel(IChannel):
    """Канал-шпион — тот же примитив, что в характеризации доставки (Ф4.1)."""

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


def _logger(
    channels: List[str],
    min_level: str = "DEBUG",
    **sampling_kwargs: Any,
) -> LoggerCore:
    """Логгер без буфера + поля sampling_* из контракта, если переданы."""
    config: Dict[str, Any] = {
        "app_name": "sampling_contract",
        "enable_batching": False,
        "modules": {},
        "channels": {},
        "scopes": {"SYSTEM": {"enabled": True, "min_level": min_level, "channels": list(channels)}},
    }
    config.update(sampling_kwargs)
    mgr = LoggerCore(manager_name="SamplingContractLogger", config=config)
    mgr.initialize()
    return mgr


def _register_spy(mgr: LoggerCore, name: str) -> _SpyChannel:
    spy = _SpyChannel(name)
    mgr.register_channel(spy)
    return spy


# ---------------------------------------------------------------------------
# 1. sampling_first_n=0 — сэмплинг выключен, поведение как без него
# ---------------------------------------------------------------------------


class TestSamplingDisabled:
    def test_first_n_zero_delivers_every_identical_record(self) -> None:
        """Дефолт (``first_n=0``) — сколько послали, столько и доехало."""
        mgr = _logger(["a"], sampling_first_n=0)
        spy = _register_spy(mgr, "a")

        for _ in range(10):
            mgr.log("SYSTEM", LogLevel.DEBUG, "повтор без дросселя", "mod")

        assert len(spy.written) == 10
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 2. первые first_n проходят всегда, следующая подавляется
# ---------------------------------------------------------------------------


class TestFirstNAlwaysPass:
    def test_first_n_pass_then_next_is_suppressed(self) -> None:
        mgr = _logger(["a"], sampling_first_n=2, sampling_every_mth=1_000_000)
        spy = _register_spy(mgr, "a")

        for _ in range(3):
            mgr.log("SYSTEM", LogLevel.DEBUG, "ровно N плюс один", "mod")

        assert len(spy.written) == 2, (
            f"ожидались ровно первые 2 записи (first_n=2), а every_mth=1e6 "
            f"гарантирует, что третья не может пройти по 'каждой M-й'; дошло {len(spy.written)}"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 3. после первых N — каждая M-я, число литералом на конкретной серии
# ---------------------------------------------------------------------------


class TestEveryMthAfterFirstN:
    def test_exact_count_on_a_concrete_series(self) -> None:
        """first_n=1, every_mth=2, 6 одинаковых записей подряд.

        Модель критерия (см. докстринг модуля): #1 проходит (first_n).
        Из оставшихся пяти (относительные индексы 1..5) проходят те, чей
        относительный индекс кратен 2 — это #2(rel=1,нет), #3(rel=2,да),
        #4(rel=3,нет), #5(rel=4,да), #6(rel=5,нет). Итого 1 + 2 = 3 из 6.
        """
        mgr = _logger(["a"], sampling_first_n=1, sampling_every_mth=2)
        spy = _register_spy(mgr, "a")

        for _ in range(6):
            mgr.log("SYSTEM", LogLevel.DEBUG, "серия для every_mth", "mod")

        assert len(spy.written) == 3, (
            f"ожидалось 3 прошедших записи из 6 (first_n=1, every_mth=2), дошло {len(spy.written)}"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 4. ERROR/CRITICAL никогда не подавляются; уровень выше max_level — тоже
# ---------------------------------------------------------------------------


class TestNeverSampledLevels:
    def test_critical_is_never_suppressed_even_if_max_level_raised(self) -> None:
        """Попытка поднять потолок до CRITICAL не включает дроссель для CRITICAL."""
        mgr = _logger(
            ["a"],
            sampling_first_n=1,
            sampling_every_mth=1000,
            sampling_max_level="CRITICAL",
        )
        spy = _register_spy(mgr, "a")

        for _ in range(5):
            mgr.log("SYSTEM", LogLevel.CRITICAL, "критическая всегда доезжает", "mod")

        assert len(spy.written) == 5, f"CRITICAL обязан обходить дроссель всегда, дошло {len(spy.written)}"
        mgr.shutdown()

    def test_error_is_never_suppressed_even_if_max_level_raised(self) -> None:
        mgr = _logger(
            ["a"],
            sampling_first_n=1,
            sampling_every_mth=1000,
            sampling_max_level="CRITICAL",
        )
        spy = _register_spy(mgr, "a")

        for _ in range(5):
            mgr.log("SYSTEM", LogLevel.ERROR, "ошибка всегда доезжает", "mod")

        assert len(spy.written) == 5, f"ERROR обязан обходить дроссель всегда, дошло {len(spy.written)}"
        mgr.shutdown()

    def test_level_above_default_max_level_is_never_sampled(self) -> None:
        """Дефолт ``sampling_max_level='DEBUG'`` — WARNING его не касается."""
        mgr = _logger(["a"], sampling_first_n=1, sampling_every_mth=1000)
        spy = _register_spy(mgr, "a")

        for _ in range(5):
            mgr.log("SYSTEM", LogLevel.WARNING, "выше потолка дросселя", "mod")

        assert len(spy.written) == 5, (
            f"WARNING выше sampling_max_level=DEBUG обязан идти мимо дросселя, дошло {len(spy.written)}"
        )
        mgr.shutdown()

    def test_unknown_level_name_in_config_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="неизвестный уровень"):
            LoggerManagerConfig(sampling_max_level="ОПЕЧАТКА")

    def test_level_synonyms_are_accepted_and_normalized(self) -> None:
        cfg_warn = LoggerManagerConfig(sampling_max_level="warn")
        cfg_fatal = LoggerManagerConfig(sampling_max_level="fatal")

        assert cfg_warn.sampling_max_level == "WARNING"
        assert cfg_fatal.sampling_max_level == "CRITICAL"


# ---------------------------------------------------------------------------
# 5. разный текст или разный уровень при одинаковом тексте — разные события
# ---------------------------------------------------------------------------


class TestDifferentKeysAreIndependent:
    def test_different_message_text_has_its_own_budget(self) -> None:
        mgr = _logger(["a"], sampling_first_n=1, sampling_every_mth=1000)
        spy = _register_spy(mgr, "a")

        mgr.log("SYSTEM", LogLevel.DEBUG, "сообщение А", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "сообщение А", "mod")  # подавлена
        mgr.log("SYSTEM", LogLevel.DEBUG, "сообщение Б", "mod")  # свой бюджет — проходит
        mgr.log("SYSTEM", LogLevel.DEBUG, "сообщение Б", "mod")  # подавлена

        messages = [rec["message"] for rec in spy.written]
        assert messages == ["сообщение А", "сообщение Б"], (
            f"каждый текст обязан получить свой first_n=1 независимо от соседа, дошло {messages}"
        )
        mgr.shutdown()

    def test_same_text_different_level_has_its_own_budget(self) -> None:
        """Ключ — пара (уровень, текст): поднимаем потолок до WARNING, чтобы оба уровня дросселировались."""
        mgr = _logger(
            ["a"],
            sampling_first_n=1,
            sampling_every_mth=1000,
            sampling_max_level="WARNING",
        )
        spy = _register_spy(mgr, "a")

        mgr.log("SYSTEM", LogLevel.DEBUG, "общий текст", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "общий текст", "mod")  # подавлена (2-я DEBUG)
        mgr.log("SYSTEM", LogLevel.INFO, "общий текст", "mod")  # другой уровень — свой бюджет

        levels = [rec["level"] for rec in spy.written]
        assert len(spy.written) == 2, (
            f"(DEBUG,'общий текст') и (INFO,'общий текст') обязаны быть разными ключами, "
            f"дошло {len(spy.written)} записей уровней {levels}"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 6. burst: тишина дольше burst_reset_sec начинает серию заново
# ---------------------------------------------------------------------------


class TestBurstReset:
    def test_silence_longer_than_reset_restarts_the_burst(self) -> None:
        """Часы не патчатся глобально — окно двигает реальный ``time.sleep``."""
        mgr = _logger(
            ["a"],
            sampling_first_n=1,
            sampling_every_mth=1_000_000,
            sampling_burst_reset_sec=0.05,
        )
        spy = _register_spy(mgr, "a")

        mgr.log("SYSTEM", LogLevel.DEBUG, "всплеск", "mod")  # 1: проходит (first_n)
        mgr.log("SYSTEM", LogLevel.DEBUG, "всплеск", "mod")  # 2: подавлена, бюджет исчерпан

        time.sleep(0.2)  # дольше burst_reset_sec=0.05 — тишина должна сбросить окно

        mgr.log("SYSTEM", LogLevel.DEBUG, "всплеск", "mod")  # 3: обязана снова пройти как first_n

        assert len(spy.written) == 2, (
            f"ожидались записи #1 и #3 (после тишины дольше burst_reset_sec), дошло {len(spy.written)}"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 7. подавление видно снаружи через get_stats()
# ---------------------------------------------------------------------------


class TestStatsVisibility:
    def test_sampling_keys_present_as_zero_when_nothing_suppressed(self) -> None:
        """Ключи есть ВСЕГДА (нулями), не только по факту потери."""
        mgr = _logger(["a"], sampling_first_n=0)
        _register_spy(mgr, "a")

        mgr.log("SYSTEM", LogLevel.DEBUG, "без подавлений", "mod")

        stats = mgr.get_stats()
        assert "records_sampled_out" in stats
        assert "sampler_keys_tracked" in stats
        assert "sampler_keys_saturated" in stats
        assert stats["records_sampled_out"] == 0
        assert stats["sampler_keys_saturated"] == 0
        mgr.shutdown()

    def test_suppression_increments_sampled_out_and_processor_drop_counter(self) -> None:
        mgr = _logger(["a"], sampling_first_n=1, sampling_every_mth=1_000_000)
        _register_spy(mgr, "a")
        before = mgr.get_stats()
        before_sampled_out = before["records_sampled_out"]
        before_dropped = before["records_dropped_by_processor"]

        mgr.log("SYSTEM", LogLevel.DEBUG, "подавляемая пара", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "подавляемая пара", "mod")  # подавлена

        after = mgr.get_stats()
        assert after["records_sampled_out"] == before_sampled_out + 1
        assert after["records_dropped_by_processor"] == before_dropped + 1, (
            "подавление обязано увеличивать уже существующий records_dropped_by_processor"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 8. прошедшая запись несёт extra['sampled_skipped']
# ---------------------------------------------------------------------------


class TestSampledSkippedField:
    def test_passed_record_carries_count_of_suppressed_since_last_pass(self) -> None:
        """first_n=1, every_mth=3: #1 проходит, #2 и #3 подавлены, #4 проходит.

        На #4 ``extra['sampled_skipped']`` обязан быть 2 (подавлены #2 и #3).
        """
        mgr = _logger(["a"], sampling_first_n=1, sampling_every_mth=3)
        spy = _register_spy(mgr, "a")

        for _ in range(4):
            mgr.log("SYSTEM", LogLevel.DEBUG, "с полем sampled_skipped", "mod")

        assert len(spy.written) == 2, f"ожидались #1 и #4, дошло {len(spy.written)}"
        second_delivered = spy.written[1]
        assert second_delivered["extra"].get("sampled_skipped") == 2, (
            f"ожидалось extra['sampled_skipped']=2 на записи, прошедшей после двух подавлений, "
            f"получено {second_delivered['extra'].get('sampled_skipped')!r}"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 9. дроссель не портит общую запись — все каналы видят одинаковое содержимое
# ---------------------------------------------------------------------------


class TestSharedRecordNotMutated:
    def test_all_channels_see_equal_content_for_a_record_that_passed_after_suppressions(self) -> None:
        mgr = _logger(["a", "b"], sampling_first_n=1, sampling_every_mth=2)
        spy_a = _register_spy(mgr, "a")
        spy_b = _register_spy(mgr, "b")

        for _ in range(3):
            mgr.log("SYSTEM", LogLevel.DEBUG, "общая запись после подавлений", "mod")

        assert len(spy_a.written) == len(spy_b.written) == 2
        for rec_a, rec_b in zip(spy_a.written, spy_b.written):
            assert rec_a == rec_b, "два канала одного скоупа обязаны получить идентичное содержимое"
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 10. reconfigure не сбрасывает окно дросселя
# ---------------------------------------------------------------------------


class TestReconfigureDoesNotResetWindow:
    def test_window_survives_reconfigure_with_same_sampling_settings(self) -> None:
        config: Dict[str, Any] = {
            "app_name": "sampling_contract",
            "enable_batching": False,
            "modules": {},
            "channels": {},
            "scopes": {"SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]}},
            "sampling_first_n": 1,
            "sampling_every_mth": 1_000_000,
        }
        mgr = LoggerCore(manager_name="ReconfigureSamplingLogger", config=dict(config))
        mgr.initialize()
        spy_before = _register_spy(mgr, "a")

        mgr.log("SYSTEM", LogLevel.DEBUG, "переживает reconfigure", "mod")
        assert len(spy_before.written) == 1, "первая запись обязана пройти по first_n=1"

        ok = mgr.reconfigure(dict(config))
        assert ok is True, "reconfigure с валидным конфигом обязан вернуть True"

        # reconfigure закрывает и чистит реестр каналов (full-rebuild) — шпион
        # регистрируется заново под тем же именем.
        spy_after = _register_spy(mgr, "a")
        stats_before = mgr.get_stats()["records_sampled_out"]

        mgr.log("SYSTEM", LogLevel.DEBUG, "переживает reconfigure", "mod")

        stats_after = mgr.get_stats()["records_sampled_out"]
        assert spy_after.written == [], (
            "окно дросселя обязано пережить reconfigure: вторая одинаковая запись "
            "после reconfigure не должна снова получить свежий first_n"
        )
        assert stats_after == stats_before + 1, "подавление после reconfigure обязано быть учтено в статистике"
        mgr.shutdown()
