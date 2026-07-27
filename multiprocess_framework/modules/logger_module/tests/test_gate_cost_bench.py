# -*- coding: utf-8 -*-
"""Ф1.6 — цена гейта: сколько стоит отклонённая и принятая запись.

**Как читать этот файл.** Абсолютные миллисекунды на разных машинах разные, и
порог, прибитый числом, либо мигает, либо ничего не сторожит. Поэтому «до»
измеряется В ТОМ ЖЕ ПРОГОНЕ: рядом лежит эталонная реализация прежнего гейта
(``_LegacyGate`` — f-string как ключ кэша и ``LEVEL_ORDER.index(str)`` на
решении), и регресс определяется как «новый путь стал медленнее старого».
Такой порог самокалибруется и на медленной CI-машине, и на быстром ноутбуке.

Отдельно проверяется свойство, которое временем не измеряется вовсе:
**на пути решения не строится ни одной строки**. Инструмент — подкласс ``str``,
считающий обращения к ``.upper()``, а НЕ ``tracemalloc``: снимок сравнивает
живую память, а строка от ``.upper()`` умирает в той же инструкции, поэтому на
2000 вызовах прежней реализации диффы показывали ноль байт — «доказательство»
было бы вакуумным. ``tracemalloc`` остался только там, где он к месту: проверить,
что кэшированный путь ничего не УДЕРЖИВАЕТ (это про утечку, а не про транзиент).

Числа последнего замера (Windows 10, Python 3.12, 2026-07-27) занесены в
plans/observability-unified-routing.md, Ф1.6.
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerScopeSchema
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

_LEGACY_LEVEL_ORDER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class _LegacyScopeSchema(LoggerScopeSchema):
    """Прежнее ``should_log`` — на ТОЙ ЖЕ Pydantic-модели.

    Наследование, а не голый объект: первая редакция бенча сравнивала новый код
    на ``LoggerScopeSchema`` со старым на обычном классе и мерила разницу между
    Pydantic и не-Pydantic, а не между двумя реализациями. Сравнение обязано
    отличаться ровно телом метода.
    """

    def should_log(self, level: LogLevel, module: str) -> bool:
        if not self.enabled:
            return False
        try:
            lv = _LEGACY_LEVEL_ORDER.index(level.value)
            mv = _LEGACY_LEVEL_ORDER.index(self.min_level.upper())
        except ValueError:
            return True
        if lv < mv:
            return False
        if self.modules and module not in self.modules:
            return False
        return True


class _LegacyGate:
    """Эталон «до Ф1» на уровне менеджера: строковый ключ кэша.

    Копия, а не импорт: прежней реализации в дереве больше нет, а сравнивать
    надо именно с ней. Копия узкая — только путь решения, ничего вокруг.
    """

    def __init__(self, min_level: str = "INFO", modules: Tuple[str, ...] = ()) -> None:
        self.schema = _LegacyScopeSchema(enabled=True, min_level=min_level, modules=list(modules))
        self.cache: Dict[str, bool] = {}

    def _direct(self, level: LogLevel, module: str) -> bool:
        return self.schema.should_log(level, module)

    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        key = f"{scope.value}:{level.value}:{module}"
        if key in self.cache:
            return self.cache[key]
        result = self._direct(level, module)
        self.cache[key] = result
        return result


def _timed(fn, repeats: int) -> float:
    """Секунд на вызов. Три прогона, берём лучший — шум ОС режется минимумом."""
    best = None
    for _ in range(3):
        start = time.perf_counter()
        for _ in range(repeats):
            fn()
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best / repeats


@pytest.fixture
def logger(tmp_path: Path):
    mgr = LoggerManager(
        manager_name="BenchProbe",
        config={
            "app_name": "bench",
            "log_directory": str(tmp_path),
            "enable_batching": True,
            "modules": {},
            "channels": {
                "sink": {
                    "type": "file",
                    "enabled": True,
                    "file_path": str(tmp_path / "bench.log"),
                    "format": "%(message)s",
                },
            },
            "scopes": {
                # BUSINESS принимает INFO, DEBUG-скоуп выключен — две ветки бенча.
                "BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["sink"]},
                "DEBUG": {"enabled": False, "min_level": "DEBUG", "channels": ["sink"]},
            },
        },
    )
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class _CountingStr(str):
    """Строка, считающая обращения к ``.upper()``.

    Инструмент выбран после неудачи с ``tracemalloc``: снимок меряет ЖИВУЮ
    память, а строка от ``.upper()`` умирает в той же инструкции — на 2000
    вызовах прежней реализации диффы показывали ноль байт, и «доказательство»
    было бы вакуумным. Здесь считается сама операция, и счёт накопительный.
    """

    calls = 0

    def upper(self) -> str:  # type: ignore[override]
        type(self).calls += 1
        return str.upper(self)


class TestGateDoesNotAllocatePerDecision:
    """1.1-1.2 — цена отклонённой записи не включает построение строк."""

    def test_decision_path_does_not_call_upper_and_legacy_did(self, capsys: pytest.CaptureFixture) -> None:
        """Пара: новый путь ``.upper()`` не зовёт, прежний — зовёт на каждом решении.

        Одна половина без второй ничего не значила бы: ноль мог бы означать
        «инструмент смотрит не туда». Схемы строятся через ``model_construct``,
        иначе Pydantic привёл бы подкласс к обычному ``str`` и счётчик замолчал
        бы по совсем другой причине.
        """

        def _upper_calls(schema_cls: type, level_name: str) -> int:
            class _Probe(_CountingStr):
                calls = 0

            schema = schema_cls.model_construct(enabled=True, min_level=_Probe(level_name), modules=[])
            for _ in range(100):
                schema.should_log(LogLevel.DEBUG, "bench_mod")
            return _Probe.calls

        new = _upper_calls(LoggerScopeSchema, "INFO")
        old = _upper_calls(_LegacyScopeSchema, "INFO")

        with capsys.disabled():
            print(f"  .upper() на 100 решений: было {old} → стало {new}")

        assert old == 100, "эталон не зовёт .upper() — инструмент смотрит не туда"
        assert new == 0, f"решение всё ещё строит строку: {new} вызовов .upper()"

    def test_ranks_table_is_the_live_mechanism(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Позитивная половина: решение действительно берётся из таблицы рангов.

        Без неё «нет .upper()» согласовалось бы и с реализацией, которая просто
        всегда возвращает False. Подменяем таблицу — решение обязано измениться.
        """
        from multiprocess_framework.modules.logger_module.configs import logger_manager_config as cfg

        schema = LoggerScopeSchema(enabled=True, min_level="WARNING")
        assert schema.should_log(LogLevel.INFO, "bench_mod") is False

        monkeypatch.setattr(cfg, "LEVEL_RANKS", {"INFO": 9, "WARNING": 2})
        assert schema.should_log(LogLevel.INFO, "bench_mod") is True

    def test_cached_manager_path_does_not_retain_memory(self, logger: LoggerManager) -> None:
        """Повторная отклонённая запись не наращивает удержанную память.

        Это про утечку, а не про транзиентные аллокации: ``tracemalloc``
        сравнивает живые блоки, и рост здесь означал бы, что гейт что-то
        копит на каждое решение.
        """
        scope, level, module = LogScope.DEBUG, LogLevel.DEBUG, "bench_mod"
        assert logger.should_log(scope, level, module) is False, "предусловие: гейт закрыт"

        tracemalloc.start()
        try:
            before = tracemalloc.take_snapshot()
            for _ in range(2000):
                logger.should_log(scope, level, module)
            after = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()

        offenders = [
            stat
            for stat in after.compare_to(before, "lineno")
            if "logger_core.py" in str(stat.traceback) and stat.size_diff > 0
        ]
        assert offenders == [], "гейт удерживает память на закэшированном пути: " + "; ".join(
            f"{s.traceback} +{s.size_diff}B ×{s.count_diff}" for s in offenders
        )

    def test_cache_key_is_not_a_string(self, logger: LoggerManager) -> None:
        """1.2 напрямую: ключ не строится склейкой, значит и не аллоцируется."""
        logger.invalidate_decision_cache()
        for _ in range(10):
            logger.should_log(LogScope.DEBUG, LogLevel.DEBUG, "bench_mod")

        assert len(logger._decision_cache) == 1, "кэш не сработал — тест проверял бы не то"
        assert all(isinstance(key, tuple) for key in logger._decision_cache)


class TestGateIsNotSlowerThanBefore:
    """1.6 — регресс-порог относительный: новый путь не медленнее прежнего."""

    REPEATS = 20_000
    #: Запас на шум измерения. Меньше 1.0 требовать нельзя: цель Ф1 —
    #: «не дороже», ускорение приятно, но не гарантировано на всякой машине.
    TOLERANCE = 1.10

    def test_rejected_record_gate(self, logger: LoggerManager, capsys: pytest.CaptureFixture) -> None:
        legacy = _LegacyGate(min_level="WARNING")
        scope, level, module = LogScope.DEBUG, LogLevel.DEBUG, "bench_mod"

        # Прогреть оба кэша — меряем именно установившийся путь.
        logger.should_log(scope, level, module)
        legacy.should_log(scope, level, module)

        new = _timed(lambda: logger.should_log(scope, level, module), self.REPEATS)
        old = _timed(lambda: legacy.should_log(scope, level, module), self.REPEATS)

        with capsys.disabled():
            print(f"\n  гейт отклонённой записи: было {old * 1e9:.0f} нс → стало {new * 1e9:.0f} нс")

        assert new <= old * self.TOLERANCE, f"гейт стал дороже прежнего: {new * 1e9:.0f} нс против {old * 1e9:.0f} нс"

    #: Допуск для СХЕМЫ отдельно и он широкий — так и задумано.
    #: Замер: 338 нс против 330 нс, то есть паритет в пределах 2 %.
    #: С допуском 1.10 тест умирал от инъекций, к нему отношения не имевших
    #: (например «forget_channel ничего не забывает») — классический флейк:
    #: порог 10 % при фактическом запасе 2 %. Здесь сторожится не микро-выигрыш
    #: (его на этом уровне нет — см. ``test_decision_path_does_not_call_upper``),
    #: а МАТЕРИАЛЬНЫЙ регресс: возврат к линейным поискам плюс построение
    #: строки внутри цикла дал бы кратную, а не процентную разницу.
    SCHEMA_TOLERANCE = 1.5

    def test_scope_schema_decision(self, logger: LoggerManager, capsys: pytest.CaptureFixture) -> None:
        """Некэшированное решение — то, что считает сам ``LoggerScopeSchema``."""
        legacy = _LegacyGate(min_level="INFO")
        schema = logger.config.scopes["BUSINESS"]

        new = _timed(lambda: schema.should_log(LogLevel.DEBUG, "bench_mod"), self.REPEATS)
        old = _timed(lambda: legacy._direct(LogLevel.DEBUG, "bench_mod"), self.REPEATS)

        with capsys.disabled():
            print(f"  решение скоупа:          было {old * 1e9:.0f} нс → стало {new * 1e9:.0f} нс")

        assert new <= old * self.SCHEMA_TOLERANCE, (
            f"решение скоупа стало кратно дороже: {new * 1e9:.0f} нс против {old * 1e9:.0f} нс"
        )


class TestRecordCost:
    """Цена целой записи — отклонённой и принятой. Информационный замер + потолок."""

    REPEATS = 5_000

    def test_rejected_record_is_much_cheaper_than_accepted(
        self, logger: LoggerManager, capsys: pytest.CaptureFixture
    ) -> None:
        rejected = _timed(
            lambda: logger.log(LogScope.DEBUG, LogLevel.DEBUG, "отклонённая", "bench_mod"),
            self.REPEATS,
        )
        accepted = _timed(
            lambda: logger.log(LogScope.BUSINESS, LogLevel.INFO, "принятая", "bench_mod"),
            self.REPEATS,
        )
        logger.flush()

        with capsys.disabled():
            print(f"  запись отклонена:        {rejected * 1e6:.2f} мкс")
            print(f"  запись принята:          {accepted * 1e6:.2f} мкс")

        assert rejected < accepted, "отклонённая запись обязана быть дешевле принятой"

    def test_lazy_message_costs_the_same_as_a_ready_string_when_rejected(
        self, logger: LoggerManager, capsys: pytest.CaptureFixture
    ) -> None:
        """Ленивое сообщение не добавляет цены отклонённой записи.

        Смысл 1.4: callable — это способ НЕ платить, и сам он платы стоить не
        должен. Порог щедрый (×1.5): здесь важен порядок величины, а не проценты.
        """
        ready = _timed(
            lambda: logger.log(LogScope.DEBUG, LogLevel.DEBUG, "готовая строка", "bench_mod"),
            self.REPEATS,
        )
        lazy = _timed(
            lambda: logger.log(LogScope.DEBUG, LogLevel.DEBUG, lambda: "дорогая строка", "bench_mod"),
            self.REPEATS,
        )

        with capsys.disabled():
            print(f"  отклонена (готовая):     {ready * 1e6:.2f} мкс")
            print(f"  отклонена (callable):    {lazy * 1e6:.2f} мкс")

        assert lazy <= ready * 1.5


class TestNoRecordIsLostByTheBench:
    """Страж самих бенчей: они не должны молча ничего терять.

    Бенч, гоняющий тысячи записей мимо счётчиков, — идеальное место спрятать
    регресс учёта. Проверяем, что все четыре класса потери остались нулевыми.
    """

    def test_counters_stay_clean(self, logger: LoggerManager) -> None:
        for _ in range(200):
            logger.log(LogScope.BUSINESS, LogLevel.INFO, "учёт", "bench_mod")
        logger.flush()

        stats: Dict[str, Any] = logger.get_stats()
        losses: List[str] = [
            key
            for key in (
                "unresolved_channel_records",
                "records_without_channels",
                "channel_refused_records",
                "channel_write_errors",
            )
            if stats[key]
        ]
        assert losses == [], f"бенч потерял записи: {[(k, stats[k]) for k in losses]}"
