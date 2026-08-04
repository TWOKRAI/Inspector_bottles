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

import sys
import time
import tracemalloc
from enum import Enum
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

    def should_log(self, scope: str, level: LogLevel, module: str) -> bool:
        # Ф2.4: скоуп приезжает строкой. Эталон продолжает делать то, что делал
        # «до Ф1» — СКЛЕИВАТЬ ключ; в этом и была его цена, а не в `.value`.
        key = f"{scope}:{level.value}:{module}"
        if key in self.cache:
            return self.cache[key]
        result = self._direct(level, module)
        self.cache[key] = result
        return result


def _report(capsys: "pytest.CaptureFixture", line: str) -> None:
    """Напечатать строку замера мимо capture — БЕЗОПАСНО для дефолтной консоли.

    ``capsys.disabled()`` пишет в настоящий ``sys.stdout``, а он на штатной
    платформе проекта (Windows, `scripts/run_framework_tests.py` без
    ``PYTHONIOENCODING``) в cp1251. Первая редакция печатала стрелку ``\\u2192``
    и роняла три теста ``UnicodeEncodeError`` — то есть «5862 passed» было
    верно только под utf-8. Ровно тот класс, что записан в памяти проекта
    («русский вывод в cp866 = инструмент молчал у потребителя»), и найден он
    ревью, а не мной.

    Кодировка снимается ВНУТРИ ``capsys.disabled()`` — и это не косметика.
    Первая редакция фикса читала ``sys.stdout.encoding`` ДО входа в блок, то
    есть у capture-объекта pytest, у которого он всегда ``UTF-8``:
    ``encode("UTF-8").decode("UTF-8")`` — тождество, и защиты не было вовсе.
    Красный тогда снялся только заменой ``→`` на ``->``, а docstring уверял,
    что берётся «фактическая кодировка консоли». Опровергнуто второй итерацией
    ревью запуском; проверяется слом-инъекцией «вернуть ``→`` в format-строку —
    тест обязан остаться зелёным».

    Текст остаётся русским: политика языка не отменяется, отменяется только
    право теста упасть из-за собственной отладочной печати.
    """
    with capsys.disabled():
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding, errors="replace"))


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


def _timed_pair(new_fn, old_fn, repeats: int) -> tuple[float, float]:
    """Замер ДВУХ реализаций вперемежку, по секунде на вызов каждой.

    Последовательный замер («сначала три прогона нового, потом три старого»)
    сравнивает не реализации, а два разных окна загрузки машины. Ф2.1 поймала
    это на практике: ``test_rejected_record_gate`` упал в полном прогоне suite
    и прошёл в одиночку на тех же байтах кода — всплеск нагрузки пришёлся на
    окно нового пути. Чередование внутри раунда даёт обеим реализациям одни и
    те же условия; минимум по раундам, как и раньше, режет шум ОС.
    """
    best_new = best_old = None
    for _ in range(3):
        start = time.perf_counter()
        for _ in range(repeats):
            new_fn()
        new_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        for _ in range(repeats):
            old_fn()
        old_elapsed = time.perf_counter() - start

        best_new = new_elapsed if best_new is None else min(best_new, new_elapsed)
        best_old = old_elapsed if best_old is None else min(best_old, old_elapsed)
    return best_new / repeats, best_old / repeats


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

        _report(capsys, f"  .upper() на 100 решений: было {old} -> стало {new}")

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

        new, old = _timed_pair(
            lambda: logger.should_log(scope, level, module),
            lambda: legacy.should_log(scope, level, module),
            self.REPEATS,
        )

        _report(capsys, f"\n  гейт отклонённой записи: было {old * 1e9:.0f} нс -> стало {new * 1e9:.0f} нс")

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

        new, old = _timed_pair(
            lambda: schema.should_log(LogLevel.DEBUG, "bench_mod"),
            lambda: legacy._direct(LogLevel.DEBUG, "bench_mod"),
            self.REPEATS,
        )

        _report(capsys, f"  решение скоупа:          было {old * 1e9:.0f} нс -> стало {new * 1e9:.0f} нс")

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

        _report(capsys, f"  запись отклонена:        {rejected * 1e6:.2f} мкс")
        _report(capsys, f"  запись принята:          {accepted * 1e6:.2f} мкс")

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

        _report(capsys, f"  отклонена (готовая):     {ready * 1e6:.2f} мкс")
        _report(capsys, f"  отклонена (callable):    {lazy * 1e6:.2f} мкс")

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


# =============================================================================
# 2.2 — хэш ключа кэша решений
# =============================================================================


class _DefaultHashLevel(Enum):
    """Двойник ``LogLevel`` с ШТАТНЫМ ``Enum.__hash__`` — эталон «как было».

    Отдельный enum, а не сохранённая функция: сравнивать надо стоимость поиска
    в словаре по такому ключу, а подмена ``__hash__`` на живом ``LogLevel``
    испортила бы кэши всего процесса на время замера.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"


class _DefaultHashScope(Enum):
    SYSTEM = "system"
    DEBUG = "debug"


class TestGateKeyHashIsIdentity:
    """Ключ кэша решений хэшируется по identity, а не через ``Enum.__hash__``.

    Свойство измеряемое, поэтому и проверяется замером, а не именем метода:
    утверждение ``LogLevel.__hash__ is object.__hash__`` сторожило бы имя, а не
    выигрыш, и осталось бы зелёным, если кто-то поставит туда свою «быструю»
    функцию, которая на деле медленнее.

    Порог самокалибруется: рядом лежит двойник со штатным хэшем, и оба ключа
    меряются вперемежку в одном прогоне (см. :func:`_timed_pair`).
    """

    #: Во сколько раз ключ из живых enum'ов обязан обгонять ключ из двойника.
    #: Измерено 7×; порог 2× — запас на медленную и шумную машину. Узкий допуск
    #: на этом проекте уже давал флейк (Ф2.1, стоимость штампа).
    SPEEDUP_FLOOR = 2.0

    def test_key_lookup_beats_the_default_enum_hash(self, capsys) -> None:
        fast_key = (LogScope.DEBUG, LogLevel.DEBUG, "bench_mod")
        slow_key = (_DefaultHashScope.DEBUG, _DefaultHashLevel.DEBUG, "bench_mod")
        fast_map = {fast_key: True}
        slow_map = {slow_key: True}

        fast, slow = _timed_pair(lambda: fast_map.get(fast_key), lambda: slow_map.get(slow_key), 200_000)
        _report(
            capsys,
            f"  ключ кэша, identity-хэш: {fast * 1e9:.0f} нс; "
            f"штатный Enum.__hash__: {slow * 1e9:.0f} нс; "
            f"ускорение x{slow / fast:.1f}",
        )
        assert slow / fast >= self.SPEEDUP_FLOOR, (
            f"ключ кэша перестал хэшироваться по identity: ускорение всего x{slow / fast:.1f} "
            f"(нужно >= x{self.SPEEDUP_FLOOR}). Проверь log_enums._IDENTITY_HASH."
        )

    def test_identity_hash_did_not_break_equality(self) -> None:
        """Замена корректна только пока равенство остаётся identity.

        ``Enum`` не определяет ``__eq__``, поэтому хэш по identity ему точно
        соответствует. Проверяется именно это — а не «ничего не упало».
        """
        assert LogLevel.DEBUG == LogLevel.DEBUG
        assert LogLevel.DEBUG != "DEBUG", "значение стало равно строке — identity-хэш стал некорректным"
        assert LogLevel.DEBUG != LogScope.DEBUG
        assert len({LogLevel.DEBUG, LogLevel.DEBUG, LogLevel.INFO}) == 2
        assert {LogLevel.ERROR: 1}[LogLevel.ERROR] == 1

    def test_dict_keyed_by_enum_survives_pickle(self) -> None:
        """Словарь с enum-ключами переживает pickle — это не теория.

        Хэш по identity процессный, а фреймворк spawn'ит процессы и гоняет dict
        между ними. При unpickle члены enum восстанавливаются теми же
        синглтонами своего процесса, а словарь перехэшируется — но проверить
        это надо, а не предположить: молчаливый промах ключа после unpickle
        выглядел бы как «настройка не доехала».
        """
        # pickle здесь безопасен: round-trip словаря, собранного этой же
        # строчкой, без внешних данных — воспроизводится ровно то, что делает
        # spawn с конфигом менеджера.
        import pickle  # nosec B403

        payload = {LogLevel.ERROR: "err", LogScope.BUSINESS: "biz"}
        restored = pickle.loads(pickle.dumps(payload))  # nosec B301 — свои же байты, см. выше
        assert restored[LogLevel.ERROR] == "err"
        assert restored[LogScope.BUSINESS] == "biz"


# =============================================================================
# 2.4 — скоуп строкой вместо enum'а
# =============================================================================


class _IdentityHashScope(Enum):
    """Двойник ПРЕЖНЕГО ``LogScope``: enum с хэшем по identity — эталон «до 2.4».

    Сравнивать надо именно с ним, а не со штатным ``Enum.__hash__``: до 2.4
    скоуп уже был ускорен (``_IDENTITY_HASH``), и замер против медленного
    варианта показал бы выигрыш, которого правка не делала.
    """

    SYSTEM = "system"
    DEBUG = "debug"

    __hash__ = object.__hash__


class TestScopeAsStringIsNotMoreExpensive:
    """Р-2.4-В: замена enum'а строкой не подняла цену ключа кэша.

    Утверждение «хэш строки CPython кэширует в объекте» проверяется ЗАМЕРОМ, а
    не докстрингом: прежняя редакция соседнего объяснения уверенно описывала
    хэш enum'ов неправильно, и цена той ошибки была семикратной.
    """

    #: Допуск ШИРОКИЙ, и это не послабление. Замер дал паритет (53 против 52 нс),
    #: то есть фактический запас — проценты, а при таком запасе порог 1.10
    #: сторожит шум машины: на пяти прогонах подряд он мигнул один раз, причём
    #: на инъекции, к нему отношения не имевшей. Ровно тот же случай уже разобран
    #: у ``SCHEMA_TOLERANCE`` выше, и вывод тот же — здесь сторожится не
    #: микро-выигрыш (его нет и не обещано), а МАТЕРИАЛЬНЫЙ регресс: пересборка
    #: или нормализация строки на каждом поиске дала бы кратную разницу.
    TOLERANCE = 1.5

    def test_string_key_lookup_is_not_slower_than_the_enum_key(self, capsys) -> None:
        new_key = (LogScope.DEBUG, LogLevel.DEBUG, "bench_mod")
        old_key = (_IdentityHashScope.DEBUG, LogLevel.DEBUG, "bench_mod")
        assert isinstance(new_key[0], str), "предусловие: скоуп уже строка"
        new_map = {new_key: True}
        old_map = {old_key: True}

        new, old = _timed_pair(lambda: new_map.get(new_key), lambda: old_map.get(old_key), 200_000)
        _report(
            capsys,
            f"  ключ кэша, скоуп строкой: {new * 1e9:.0f} нс; скоуп enum'ом (было): {old * 1e9:.0f} нс",
        )
        assert new <= old * self.TOLERANCE, (
            f"строка в ключе оказалась дороже enum'а: {new * 1e9:.0f} нс против {old * 1e9:.0f} нс"
        )

    def test_the_hot_path_does_not_normalize_the_scope(self, logger: LoggerManager) -> None:
        """Приведение регистра стоит на ГРАНИЦЕ конфига, а не на пути записи.

        Свойство наблюдаемое, а не имя метода: строка-шпион едет скоупом через
        настоящий ``log()`` и считает ``.upper()`` на себе. Спай на имя
        сторожил бы имя; этот ловит операцию, где бы её ни позвали — в
        ``_scope_schema``, в ``log()`` или в резолве маршрута.

        Ноль здесь значит «канон уже пришёл каноничным», и это и есть решение
        Р-2.4-А: аллокация на запись ради регистра — цена, которую платить не за
        что, когда конфиг собран один раз.
        """

        class _Probe(_CountingStr):
            calls = 0

        scope = _Probe("BUSINESS")
        for _ in range(100):
            logger.log(scope, LogLevel.INFO, "принятая", "bench_mod")
        logger.flush()

        assert _Probe.calls == 0, f"скоуп нормализуется на пути записи: {_Probe.calls} вызовов .upper()"
