# -*- coding: utf-8 -*-
"""
Тесты инвалидации decision-кэша LoggerManager/ErrorManager при runtime-смене
состава каналов (Ф0.8, план: plans/observability-unified-routing.md).

Контекст дефекта: should_log(scope, level, module) кэширует решение "писать
ли запись" по ключу (scope, level, module). Config-reload (reconfigure())
уже инвалидирует этот кэш. Runtime-смена состава каналов —
set_sink_enabled(), enable_module_logging(), disable_module_logging() —
СЕГОДНЯ кэш не трогает.

ВАЖНО — почему наивный тест здесь ничего бы не доказал:
сегодня кэшированное решение вычисляется ТОЛЬКО из scope-конфига (порог
уровня + фильтры модулей) и вообще не зависит от состава каналов. Поэтому
банальное "выключить синк → проверить, что should_log() изменился" не
может упасть НИКОГДА, вне зависимости от того, есть инвалидация или нет —
дефект латентный. Будущая фаза (Ф2.2) закэширует РАЗРЕШЁННЫЙ набор каналов
в то же решение, и вот тогда runtime-тоггл молча начнёт отдавать
устаревший ответ.

Поэтому здесь два честных способа, и оба применены:

  A. Прямое наблюдение факта инвалидации. Считаем вызовы
     _should_log_direct — это некэшированное вычисление позади
     should_log (по формулировке задачи Ф0.8 — часть контракта, а не
     деталь реализации). Кэш-хит → счётчик не растёт. После тоггла →
     счётчик обязан вырасти (значит, кэш выброшен и решение пересчитано
     заново), независимо от того, ИЗМЕНИЛОСЬ ли само булево решение.

  B. Симуляция Ф2.2. Подкласс, чьё _should_log_direct ГЕНУИННО зависит от
     текущего реестра каналов. Тогда протухание кэша реально наблюдаемо
     УЖЕ СЕГОДНЯ: закэшировать решение, дёрнуть тоггл, убедиться, что
     should_log() отражает НОВУЮ истину, а не старую.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager


_SCOPE = LogScope.SYSTEM
_LEVEL = LogLevel.INFO
_MODULE = "unit"

#: Канал из дефолтного конфига LoggerManager (см. test_sink_control.py) —
#: гарантированно существует сразу после initialize() без кастомного config.
_DEFAULT_SINK = "system_file"


class _CountingLoggerManager(LoggerManager):
    """LoggerManager, считающий обращения к некэшированному вычислению
    ОТДЕЛЬНО по ключу (scope, level, module).

    _should_log_direct назван в постановке задачи Ф0.8 как "uncached
    computation behind should_log" — то есть контрактная точка наблюдения,
    а не деталь реализации, которую нельзя трогать.

    Счётчик именно per-key, а не глобальный: initialize() сам по себе
    вызывает should_log/debug для служебных модульных каналов (router_messages,
    database, processor, ...) с ДРУГИМИ (scope, level, module) — глобальный
    счётчик ловил бы этот шум и тест был бы хрупким/неверным.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Guard ДО super(): LoggerCore.__init__ дёргает self.log()/self.debug()
        # косвенно (_setup_module_channel и т.п.), а переопределённый
        # _should_log_direct читает self.direct_calls_by_key — тот же приём,
        # что уже применён в ErrorManager.__init__ (core/error_manager.py).
        self.direct_calls_by_key: "Counter[tuple]" = Counter()
        super().__init__(*args, **kwargs)

    def _should_log_direct(self, scope, level, module):  # type: ignore[override]
        self.direct_calls_by_key[(scope, level, module)] += 1
        return super()._should_log_direct(scope, level, module)

    def calls_for(self, scope, level, module) -> int:
        return self.direct_calls_by_key[(scope, level, module)]


class _CountingErrorManager(ErrorManager):
    """Тот же per-key счётчик, но для ErrorManager — доказать общий контракт
    LoggerCore (см. docstring _CountingLoggerManager)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.direct_calls_by_key: "Counter[tuple]" = Counter()
        super().__init__(*args, **kwargs)

    def _should_log_direct(self, scope, level, module):  # type: ignore[override]
        self.direct_calls_by_key[(scope, level, module)] += 1
        return super()._should_log_direct(scope, level, module)

    def calls_for(self, scope, level, module) -> int:
        return self.direct_calls_by_key[(scope, level, module)]


class _ChannelDependentLoggerManager(LoggerManager):
    """Симуляция Ф2.2: решение should_log ГЕНУИННО зависит от состава каналов.

    Возвращает True, пока целевой канал зарегистрирован в _channel_registry.
    Сегодняшний "боевой" LoggerManager так себя не ведёт (решение не
    смотрит на реестр каналов вообще) — здесь это сделано искусственно,
    чтобы протухание кэша стало наблюдаемым уже сейчас, а не только после
    того, как Ф2.2 действительно закэширует набор каналов.
    """

    target_channel = _DEFAULT_SINK

    def _should_log_direct(self, scope, level, module):  # type: ignore[override]
        return self._channel_registry.get(self.target_channel) is not None


class TestDirectRecomputeAfterRuntimeToggle:
    """(A) Наблюдение факта инвалидации через счётчик _should_log_direct."""

    def test_cache_hit_does_not_recompute(self) -> None:
        """Не вакуумный тест: без кэша direct_calls рос бы на КАЖДЫЙ вызов
        should_log с одинаковыми аргументами. Фиксируем обратное — второй
        вызов обслужен из кэша, а не пересчитан."""
        mgr = _CountingLoggerManager(manager_name="CountCacheHit")
        mgr.initialize()
        try:
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 1

            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 1, (
                "повторный вызов с теми же аргументами обязан идти из кэша"
            )
        finally:
            mgr.shutdown()

    def test_set_sink_enabled_disable_invalidates(self) -> None:
        """Не вакуумный тест: до фикса set_sink_enabled(..., False) не трогает
        _decision_cache → direct_calls остался бы 1 (кэш отдал бы старое
        решение). После фикса — обязан вырасти до 2 (кэш выброшен, следующий
        should_log() пересчитан заново). Ожидается RED сейчас."""
        mgr = _CountingLoggerManager(manager_name="CountDisable")
        mgr.initialize()
        try:
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 1

            assert mgr.set_sink_enabled(_DEFAULT_SINK, False) is True
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 2, (
                "set_sink_enabled(False) обязан инвалидировать decision cache"
            )
        finally:
            mgr.shutdown()

    def test_set_sink_enabled_enable_invalidates(self) -> None:
        """Симметрично предыдущему — обратный тоггл (повторное enable) тоже
        обязан сбрасывать кэш. Не вакуумный тест по той же логике: без
        инвалидации direct_calls остановился бы на значении ДО этого вызова.
        Ожидается RED сейчас."""
        mgr = _CountingLoggerManager(manager_name="CountEnable")
        mgr.initialize()
        try:
            mgr.set_sink_enabled(_DEFAULT_SINK, False)
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            calls_after_disable = mgr.calls_for(_SCOPE, _LEVEL, _MODULE)
            assert calls_after_disable >= 1

            assert mgr.set_sink_enabled(_DEFAULT_SINK, True) is True
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == calls_after_disable + 1, (
                "set_sink_enabled(True) обязан инвалидировать decision cache"
            )
        finally:
            mgr.shutdown()

    def test_enable_module_logging_invalidates(self) -> None:
        """Не вакуумный тест: без инвалидации второй should_log(...) с теми же
        аргументами обслужился бы из кэша, и direct_calls не вырос бы.
        Ожидается RED сейчас."""
        mgr = _CountingLoggerManager(manager_name="CountEnableModule")
        mgr.initialize()
        try:
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 1

            mgr.enable_module_logging("probe_module")
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 2, (
                "enable_module_logging обязан инвалидировать decision cache"
            )
        finally:
            mgr.shutdown()

    def test_disable_module_logging_invalidates(self) -> None:
        """Аналогично — выключение модульного логирования обязано сбрасывать
        закэшированное решение так же, как это уже делает reconfigure().
        Ожидается RED сейчас."""
        mgr = _CountingLoggerManager(manager_name="CountDisableModule")
        mgr.initialize()
        try:
            mgr.enable_module_logging("probe_module")
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            calls_after_enable = mgr.calls_for(_SCOPE, _LEVEL, _MODULE)
            assert calls_after_enable >= 1

            mgr.disable_module_logging("probe_module")
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == calls_after_enable + 1, (
                "disable_module_logging обязан инвалидировать decision cache"
            )
        finally:
            mgr.shutdown()


class TestFailedToggleContract:
    """(2) Тоггл несуществующего синка: ничего в реестре каналов не менялось.

    Решение (пин): НЕ требуем инвалидации в этом случае — инвалидировать
    нечего, реестр каналов не изменился. Инвалидация "на всякий случай"
    тоже допустима — она безвредна (просто лишний пересчёт при следующем
    should_log). Что пиним жёстко: неудачный тоггл не имеет права сломать
    последующую корректность решения — какой бы стратегии инвалидации
    реализация ни следовала.
    """

    def test_unknown_sink_toggle_returns_false_and_preserves_correctness(self) -> None:
        """Не вакуумный тест — но не в смысле факта инвалидации, а в смысле
        зафиксированного инварианта (см. docstring класса). Упал бы, если
        неудачный тоггл сломает возвращаемое значение set_sink_enabled ИЛИ
        исказит последующий should_log (например, оставит decision cache в
        противоречивом состоянии)."""
        mgr = _ChannelDependentLoggerManager(manager_name="FailedToggle")
        mgr.initialize()
        try:
            before = mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert before is True  # _DEFAULT_SINK зарегистрирован по умолчанию

            assert mgr.set_sink_enabled("__does_not_exist__", False) is False

            after = mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert after == before, "неудачный тоггл не должен искажать решение — реестр каналов не менялся"
        finally:
            mgr.shutdown()


class TestChannelDependentDecisionStaleness:
    """(B) Симуляция Ф2.2: решение должно зависеть от РЕАЛЬНОГО состояния
    каналов на момент вызова, а не от снимка на момент первого should_log()."""

    def test_disable_channel_flips_cached_decision(self) -> None:
        """Не вакуумный тест: _ChannelDependentLoggerManager делает решение
        ГЕНУИННО зависимым от реестра каналов. Без инвалидации кэш отдал бы
        старое True даже после выключения канала — assert упал бы. С
        инвалидацией — should_log пересчитывается и видит новую истину
        (False). Ожидается RED сейчас."""
        mgr = _ChannelDependentLoggerManager(manager_name="StaleDisable")
        mgr.initialize()
        try:
            assert mgr.should_log(_SCOPE, _LEVEL, _MODULE) is True
            assert mgr._decision_cache  # решение легло в кэш

            assert mgr.set_sink_enabled(_DEFAULT_SINK, False) is True
            assert mgr.should_log(_SCOPE, _LEVEL, _MODULE) is False, (
                "should_log отдал устаревшее решение — decision cache не был "
                "инвалидирован при runtime-смене состава каналов"
            )
        finally:
            mgr.shutdown()

    def test_reenable_channel_flips_cached_decision_back(self) -> None:
        """Симметричный кейс: включение канала обратно тоже обязано сделать
        should_log видимым для новой истины (снова True), а не застрять на
        закэшированном False. Ожидается RED сейчас."""
        mgr = _ChannelDependentLoggerManager(manager_name="StaleReenable")
        mgr.initialize()
        try:
            mgr.set_sink_enabled(_DEFAULT_SINK, False)
            assert mgr.should_log(_SCOPE, _LEVEL, _MODULE) is False

            assert mgr.set_sink_enabled(_DEFAULT_SINK, True) is True
            assert mgr.should_log(_SCOPE, _LEVEL, _MODULE) is True, (
                "should_log не увидел восстановленный канал — кэш не был сброшен"
            )
        finally:
            mgr.shutdown()


class TestReconfigureRegressionGuard:
    """(4) Регресс-страж: reconfigure() уже инвалидирует кэш — это не должно
    сломаться, пока чинится runtime-тоггл каналов."""

    def test_reconfigure_recomputes_decision(self) -> None:
        """Не вакуумный тест в смысле регрессии: использует
        _CountingLoggerManager, чтобы явно увидеть пересчёт (а не косвенно
        судить по изменившемуся булеву значению, как в уже существующем
        test_logger_manager.py::test_reconfigure_invalidates_decision_cache).
        Ожидается GREEN — это уже работающее поведение."""
        mgr = _CountingLoggerManager(manager_name="ReconfigureGuard")
        mgr.initialize()
        try:
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 1

            assert mgr.reconfigure({}) is True
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr.calls_for(_SCOPE, _LEVEL, _MODULE) == 2, (
                "reconfigure обязан инвалидировать decision cache (регрессия)"
            )
        finally:
            mgr.shutdown()


class TestInvalidateDecisionCachePublicMethod:
    """(5) invalidate_decision_cache() остаётся публично вызываемым напрямую."""

    def test_direct_call_clears_cache(self) -> None:
        """Не вакуумный тест как регресс-страж: поведение уже работает
        (см. test_logger_manager.py::test_invalidate_decision_cache_clears),
        но проверяется здесь же, рядом с новыми путями инвалидации — если
        рефакторинг Ф0.8 случайно уберёт публичный метод или сломает его
        прямой вызов, этот тест упадёт первым. Ожидается GREEN."""
        mgr = LoggerManager(manager_name="DirectInvalidate")
        mgr.initialize()
        try:
            mgr.should_log(_SCOPE, _LEVEL, _MODULE)
            assert mgr._decision_cache

            mgr.invalidate_decision_cache()
            assert mgr._decision_cache == {}
        finally:
            mgr.shutdown()


class TestErrorManagerSharesInvalidationContract:
    """(6) ErrorManager делит один core (LoggerCore) с LoggerManager — контракт
    инвалидации обязан работать одинаково на обоих потомках."""

    def test_set_sink_enabled_invalidates_on_error_manager(self) -> None:
        """Не вакуумный тест: без инвалидации в LoggerCore ErrorManager
        унаследовал бы тот же дефект (кэш не трогается тогглом каналов), и
        direct_calls остался бы 1. Ожидается RED сейчас — дефект общий для
        обоих потомков LoggerCore."""
        mgr = _CountingErrorManager(manager_name="ErrCountDisable")
        mgr.initialize()
        try:
            mgr.should_log(LogScope.SYSTEM, LogLevel.ERROR, _MODULE)
            assert mgr.calls_for(LogScope.SYSTEM, LogLevel.ERROR, _MODULE) == 1

            assert mgr.set_sink_enabled("errors_file", False) is True
            mgr.should_log(LogScope.SYSTEM, LogLevel.ERROR, _MODULE)
            assert mgr.calls_for(LogScope.SYSTEM, LogLevel.ERROR, _MODULE) == 2, (
                "set_sink_enabled обязан инвалидировать decision cache и на ErrorManager"
            )
        finally:
            mgr.shutdown()
