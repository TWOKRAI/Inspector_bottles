# -*- coding: utf-8 -*-
"""Ф1.1-1.3 — гейт: ранги, ключ кэша и публичный предикат.

Три заявленных свойства, каждое проверяется отдельно (и ломается отдельно —
см. слом-инъекции в plans/observability-unified-routing.md):

  1.1  int-ранги: решение уровня не ищет строку линейным поиском и не
       аллоцирует ``.upper()``. Характеризация ПОВЕДЕНИЯ снята с прежней
       реализации, включая её странность: незнакомый уровень пропускается
       вместе с фильтром модулей.
  1.2  ключ ``_decision_cache`` — кортеж, а не f-string.
  1.3  ``is_enabled_for`` отвечает РОВНО то же, что решит ``_route`` — на
       каждой паре scope×level×module и у обоих менеджеров сразу.

Почему согласие проверяется сеткой, а не парой примеров: ``ErrorManager``
переопределяет и резолв, и гейт, и расхождение между ними было бы видно только
на конкретных сочетаниях (severity-уровень при снятом канале — ровно тот
случай, который уже один раз уронил инвариант пола).
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.levels import (
    ERROR_SEVERITY,
    SEVERITY_NUMBERS,
    UNKNOWN_SEVERITY,
    UNSPECIFIED,
    is_error_level,
    normalize_level_name,
    record_severity,
    severity_of,
    threshold_severity,
)
from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerScopeSchema
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LogLevel,
    LogScope,
    PRESET_SCOPES,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerRuleSchema
from multiprocess_framework.modules.logger_module.core.logger_core import _LEVEL_DEFAULT_SCOPE, _passes_threshold
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


# =============================================================================
# 1.1 — ранги уровней
# =============================================================================


class TestLevelRanks:
    def test_order_is_the_canonical_one(self) -> None:
        """Ф3.1: числа — словаря OTel, а не свои 0…4. Литералы обязательны.

        Прежнее ожидание выводилось из ``enumerate`` и потому соглашалось с
        ЛЮБОЙ нумерацией, включая сломанную: теста на смену чисел не было.
        """
        assert [severity_of(name) for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")] == [
            5,
            9,
            13,
            17,
            21,
        ]

    def test_unknown_level_is_distinguishable_from_debug(self) -> None:
        """Незнакомый уровень отличим и от DEBUG, и от «уровня нет вовсе».

        Если бы неизвестное совпадало с самым низким уровнем, опечатка в имени
        делала бы запись молча отфильтрованной. ``UNSPECIFIED`` (0) — третье
        состояние: у плоскости статистики оси важности нет вообще.
        """
        assert severity_of("VERBOSE") == UNKNOWN_SEVERITY
        assert severity_of("DEBUG") != UNKNOWN_SEVERITY
        assert UNKNOWN_SEVERITY != UNSPECIFIED

    def test_case_and_enum_are_both_accepted(self) -> None:
        assert severity_of("warning") == severity_of("WARNING") == severity_of(LogLevel.WARNING)

    def test_error_boundary_is_the_otel_one(self) -> None:
        """Инвариант «≥ 17 = ошибка» стал буквальным, а не совпадением."""
        assert ERROR_SEVERITY == 17
        assert is_error_level("WARNING") is False
        assert is_error_level("ERROR") is True

    def test_aliases_are_not_in_the_hot_table(self) -> None:
        """Алиасы живут на границе, а не в словаре горячего пути.

        Ключ ``WARN`` в таблице легализовал бы неканоничное имя мимо валидации
        границы и сломал бы всё производное от неё (перебор дал бы семь имён).
        """
        assert set(SEVERITY_NUMBERS) == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        assert normalize_level_name("warn") == "WARNING"
        assert normalize_level_name("FATAL") == "CRITICAL"
        assert normalize_level_name("WARNIGN") is None

    def test_record_and_threshold_positions_have_opposite_defaults(self) -> None:
        """Ф3.1: два дефолта «не понял» — по одному на позицию.

        До переномерации обе позиции обслуживала одна функция, и годилось это
        только потому, что 0 был числом DEBUG. Совпадение исчезло с DEBUG=5:
        у записи «не понял» = самый низкий уровень (доставить как DEBUG),
        у порога «не понял» = пропускать всё (fail-open, иначе опечатка = тишина).
        """
        assert record_severity("VERBOSE") == 5
        assert record_severity(None) == 5
        assert threshold_severity("VERBOSE") == 0
        assert threshold_severity(None) == 0


class TestThresholdGateCharacterization:
    """Ф8.1: ось порога одна — правило имени и его корень.

    Класс заменил ``TestScopeGateCharacterization``, характеризовавший
    ``LoggerScopeSchema.should_log``. **Свойства не выброшены вместе с
    механизмом, а переставлены на выжившую ось** — иначе снятие второй оси
    заодно и молча сняло бы всё, что она стерегла. Каждый тест ниже — тот же
    вопрос, заданный новому владельцу ответа.
    """

    def test_below_threshold_is_rejected(self) -> None:
        """Было: порог скоупа. Стало: порог правила имени."""
        assert _passes_threshold("WARNING", LogLevel.INFO) is False
        assert _passes_threshold("WARNING", LogLevel.WARNING) is True
        assert _passes_threshold("WARNING", LogLevel.CRITICAL) is True

    def test_silencing_a_group_is_now_a_threshold(self, tmp_path: Path) -> None:
        """Было: ``enabled=False`` у скоупа. Стало: порог выше уровня записи.

        Проверяется на живом менеджере, а не на схеме: выключатель был у скоупа,
        а порог — у иерархии, и утверждение «одно заменило другое» ложно, если
        оно верно только для чистой функции.
        """
        mgr = LoggerManager(
            manager_name="Silence81",
            config={
                "app_name": "silence",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "loggers": {"": {"level": "CRITICAL"}},
            },
        )
        mgr.initialize()
        try:
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.ERROR, "любой") is False
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.CRITICAL, "любой") is True
        finally:
            mgr.shutdown()

    def test_addressing_a_subtree_replaces_the_module_whitelist(self, tmp_path: Path) -> None:
        """Было: ``modules=[...]`` у скоупа (Р-2.4-Г). Стало: правило по префиксу.

        Разница не только в записи: whitelist требовал перечислить имена, а
        префикс ловит и то, чего ещё нет, — новый плагин поддерева подчиняется
        правилу без правки конфига.
        """
        mgr = LoggerManager(
            manager_name="Subtree81",
            config={
                "app_name": "subtree",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "loggers": {"": {"level": "ERROR"}, "камера": {"level": "INFO"}},
            },
        )
        mgr.initialize()
        try:
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.INFO, "камера") is True
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.INFO, "камера.видоискатель") is True
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.INFO, "гуй") is False
        finally:
            mgr.shutdown()

    def test_lowercase_level_still_works(self) -> None:
        """Нормализация имени осталась на границе — теперь у правила и у корня."""
        assert LoggerRuleSchema(level="warning").level == "WARNING"
        assert LoggerManagerConfig(default_level="warning").default_level == "WARNING"

    def test_unknown_level_is_refused_at_the_boundary(self) -> None:
        """Ф3.1 стерегла ЭТО у ``min_level``; Ф8.1 обязана стеречь у обеих новых позиций.

        Повод не теоретический и записан репро Ф3.1: ``min_level='WARN'`` давал
        ``should_log(DEBUG) = True`` — порог «предупреждения и выше» молча
        оборачивался firehose. Оставить проверку только там, откуда ось ушла,
        значило бы починить дефект на одном пути из трёх.
        """
        import pytest as _pytest

        with _pytest.raises(ValueError, match="неизвестный уровень"):
            LoggerRuleSchema(level="ОПЕЧАТКА")
        with _pytest.raises(ValueError, match="неизвестный уровень"):
            LoggerManagerConfig(default_level="ОПЕЧАТКА")

    def test_foreign_spellings_are_accepted_not_refused(self) -> None:
        """``WARN``/``FATAL`` — каноничные имена OTel, а не опечатки.

        Стоит рядом с отказом намеренно: без этой пары «строгий валидатор»
        нельзя отличить от «валидатор, отвергающий всё подряд», и первый же
        конфиг с ``WARN`` упал бы на ровном месте.
        """
        assert LoggerRuleSchema(level="WARN").level == "WARNING"
        assert LoggerRuleSchema(level="FATAL").level == "CRITICAL"

    def test_gate_stays_fail_open_when_validation_is_bypassed(self) -> None:
        """Рубеж горячего пути: минуя валидацию, незнакомый порог пропускает всё.

        Fail-closed здесь означал бы тишину от опечатки — невидимую потерю,
        запрещённую инвариантом 2 плана. Свойство перенесено с прежней ветки
        скоупа на ``_passes_threshold``, то есть на обе новые позиции сразу:
        функция одна, и разъехаться им теперь нечем.
        """
        assert _passes_threshold("ОПЕЧАТКА", LogLevel.DEBUG) is True

    @pytest.mark.parametrize(
        "снятое",
        [
            {"min_level": "ERROR"},
            {"enabled": False},
            {"modules": ["камера"]},
        ],
    )
    def test_a_removed_field_is_refused_not_ignored(self, снятое: Dict[str, Any]) -> None:
        """Снятое поле в конфиге — **отказ**, а не тихое ``extra="ignore"``.

        Без этого стража Ф8.1 создала бы дефект хуже того, что чинила: оператор
        пишет ``scopes.SYSTEM.min_level``, конфиг принят, readback показывает
        написанное — а гейт про него не знает. Это «тихая потеря адресной
        правки», один из двух исходов, ради недопущения которых 2.3b и стояла.

        Каждое поле проверяется ОТДЕЛЬНО: общая проверка «хоть одно отвергается»
        осталась бы зелёной, забудь мы в списке одно из трёх.
        """
        with pytest.raises(ValueError, match="скоуп больше не задаёт порог"):
            LoggerScopeSchema.model_validate({"channels": ["a"], **снятое})

    def test_a_removed_field_is_refused_through_the_whole_config_too(self) -> None:
        """Тот же отказ на пути ЦЕЛОГО конфига, а не только отдельной схемы.

        Пара к тесту выше и не дубль: конфиг едет через ``LoggerManagerConfig``,
        и проверка, работающая на схеме, но обойдённая сборкой, была бы
        неотличима от её отсутствия — ровно там, где конфиг и приходит.
        """
        with pytest.raises(ValueError, match="скоуп больше не задаёт порог"):
            LoggerManagerConfig.model_validate({"scopes": {"SYSTEM": {"min_level": "ERROR"}}})

    def test_an_explicit_root_rule_beats_the_default_level(self, tmp_path: Path) -> None:
        """У корня ДВА написания, и их отношение зафиксировано, а не оставлено на удачу.

        Найдено слом-инъекцией, а не чтением: инъекция «корневой порог не
        читается» (``default_level`` → всегда True) НЕ убила тест про заглушенную
        группу, хотя предсказание её называло. Причина — тест задаёт корень
        правилом ``loggers[""]``, и до ветки ``default_level`` дело не доходит.

        Это не дубль одной величины: ``default_level`` — что действует, когда про
        имя не сказало НИ ОДНО правило, а ``loggers[""]`` — правило, которое про
        имя сказало. Явное сильнее умолчания, ровно как более длинный префикс
        сильнее более короткого. Пара ниже пиннит это на случае, когда они
        РАСХОДЯТСЯ, — единственном, где разница наблюдаема.
        """
        mgr = LoggerManager(
            manager_name="RootPair81",
            config={
                "app_name": "root_pair",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "default_level": "CRITICAL",
                "loggers": {"": {"level": "DEBUG"}},
            },
        )
        mgr.initialize()
        try:
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.DEBUG, "любой") is True, (
                "явное корневое правило проиграло умолчанию default_level"
            )
        finally:
            mgr.shutdown()

    def test_without_a_root_rule_the_default_level_decides(self, tmp_path: Path) -> None:
        """Обратная половина: без правила решает ``default_level``.

        Без неё предыдущий тест зелен и у реализации, которая ``default_level``
        не читает вовсе, — то есть ровно у той, что оставила бы главную ручку
        мёртвой.
        """
        mgr = LoggerManager(
            manager_name="RootDefault81",
            config={
                "app_name": "root_default",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "default_level": "CRITICAL",
            },
        )
        mgr.initialize()
        try:
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.ERROR, "любой") is False
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.CRITICAL, "любой") is True
        finally:
            mgr.shutdown()

    def test_the_scope_no_longer_answers_about_thresholds(self) -> None:
        """Ось снята НАСОВСЕМ, и это проверяется, а не подразумевается.

        Без этого теста ничто не мешало бы вернуть ``min_level`` в схему рядом с
        новой осью — и получить обратно ровно ту коллизию, ради снятия которой
        задача делалась (репро 2026-08-04 и 2026-08-06).
        """
        assert not hasattr(LoggerScopeSchema(), "should_log")
        assert set(LoggerScopeSchema.model_fields) == {"channels"}


# =============================================================================
# 1.2 — ключ кэша решений
# =============================================================================


@pytest.fixture
def logger(tmp_path: Path) -> Any:
    mgr = LoggerManager(
        manager_name="GateProbe",
        config={"app_name": "gate", "log_directory": str(tmp_path), "enable_batching": False},
    )
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class TestDecisionCacheKey:
    def test_key_is_a_tuple_of_live_objects(self, logger: Any) -> None:
        """Ключ — кортеж, а не склеенная строка (Ф1.2)."""
        logger.invalidate_decision_cache()
        logger.should_log(LogScope.BUSINESS, LogLevel.INFO, "camera")

        keys = list(logger._decision_cache)
        assert keys == [(LogScope.BUSINESS, LogLevel.INFO, "camera")]
        assert not any(isinstance(key, str) for key in keys)

    def test_cache_answers_the_same_as_direct(self, logger: Any) -> None:
        combos = list(itertools.product(PRESET_SCOPES, LogLevel, ("main", "camera", "gui")))
        logger.invalidate_decision_cache()
        cached = [logger.should_log(s, lv, m) for s, lv, m in combos]
        direct = [logger._should_log_direct(s, lv, m) for s, lv, m in combos]
        assert cached == direct

    def test_distinct_inputs_get_distinct_entries(self, logger: Any) -> None:
        """Разные входы — разные записи кэша.

        Здесь БЫЛ тест про «склейку строкой»: якобы ключ ``"a:b"`` мог слиться
        с ``"a"``. Слом-инъекция (возврат f-string-ключа) показала, что тест
        остаётся зелёным — то есть проверял несуществующее свойство. При
        трёхчастном ключе и значениях enum без двоеточий коллизия невозможна и
        у строкового ключа тоже; выигрыш Ф1.2 — аллокация, а не различимость.
        Ложное объяснение убрано и отсюда, и из docstring'а ``should_log``.
        """
        logger.invalidate_decision_cache()
        logger.should_log(LogScope.SYSTEM, LogLevel.INFO, "a")
        logger.should_log(LogScope.SYSTEM, LogLevel.WARNING, "a")
        logger.should_log(LogScope.BUSINESS, LogLevel.INFO, "a")
        assert len(logger._decision_cache) == 3


# =============================================================================
# 1.3 — публичный предикат
# =============================================================================


def _error_manager(tmp_path: Path) -> ErrorManager:
    mgr = ErrorManager(
        config=ErrorManagerConfig(
            app_name="gate_errors",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
    )
    mgr.initialize()
    return mgr


_MODULES = ("main", "camera", "gui")


class TestIsEnabledForAgreesWithRouting:
    """Контракт 1.3: предикат обязан отвечать про ТОТ ЖЕ маршрут."""

    def test_grid_logger(self, logger: Any) -> None:
        mismatches = [
            (scope, level, module)
            for scope, level, module in itertools.product(PRESET_SCOPES, LogLevel, _MODULES)
            if logger.is_enabled_for(module, level, scope) is not (logger._route(scope, level, module) is not None)
        ]
        assert mismatches == []

    def test_grid_error_manager(self, tmp_path: Path) -> None:
        mgr = _error_manager(tmp_path)
        try:
            mismatches = [
                (scope, level, module)
                for scope, level, module in itertools.product(PRESET_SCOPES, LogLevel, _MODULES)
                if mgr.is_enabled_for(module, level, scope) is not (mgr._route(scope, level, module) is not None)
            ]
            assert mismatches == []
        finally:
            mgr.shutdown()

    def test_grid_error_manager_with_all_sinks_removed(self, tmp_path: Path) -> None:
        """Согласие обязано держаться и когда severity-каналов не осталось.

        Именно это сочетание уронило инвариант пола при первой редакции P2:
        гейт закрывался, ``_route`` уходил к родителю, ERROR исчезал молча.
        """
        mgr = _error_manager(tmp_path)
        try:
            for name in list(mgr._channel_registry.names()):
                mgr.set_sink_enabled(name, False)

            mismatches = [
                (scope, level, module)
                for scope, level, module in itertools.product(PRESET_SCOPES, LogLevel, _MODULES)
                if mgr.is_enabled_for(module, level, scope) is not (mgr._route(scope, level, module) is not None)
            ]
            assert mismatches == []
            assert mgr.is_enabled_for("main", LogLevel.ERROR) is True, (
                "ошибка обязана считаться разрешённой даже без единого приёмника — её ждёт пол"
            )
        finally:
            mgr.shutdown()

    def test_default_scope_matches_convenience_methods(self, tmp_path: Path) -> None:
        """Таблица ``_LEVEL_DEFAULT_SCOPE`` сверяется с ФАКТОМ, а не с намерением.

        Для каждого уровня: предикат без ``scope`` обязан совпасть с тем,
        записал ли что-нибудь одноимённый удобный метод. Иначе предикат
        «дешёвый», но про другую запись.
        """
        written: List[Dict[str, Any]] = []
        mgr = LoggerManager(
            manager_name="ScopeMatch",
            config={
                "app_name": "scope_match",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                # DEBUG-скоуп включаем: иначе половина сетки зелёная по одной
                # и той же причине «всё выключено».
                "default_level": "DEBUG",
                "scopes": {
                    "SYSTEM": {"channels": ["probe"]},
                    "BUSINESS": {"channels": ["probe"]},
                    "DEBUG": {"channels": ["probe"]},
                },
                "channels": {"probe": {"type": "file", "enabled": True, "file_path": str(tmp_path / "p.log")}},
                "modules": {},
            },
        )
        mgr.initialize()
        try:
            channel = mgr._channel_registry.get("probe")
            original_write = channel.write

            def _spy(record: Dict[str, Any]) -> Dict[str, Any]:
                written.append(record)
                return original_write(record)

            channel.write = _spy  # type: ignore[method-assign]

            for method, level in (
                ("debug", LogLevel.DEBUG),
                ("info", LogLevel.INFO),
                ("warning", LogLevel.WARNING),
                ("error", LogLevel.ERROR),
                ("critical", LogLevel.CRITICAL),
            ):
                written.clear()
                predicted = mgr.is_enabled_for("probe_mod", level)
                getattr(mgr, method)(f"проверка {method}", module="probe_mod")
                assert predicted is bool(written), (
                    f"is_enabled_for обещал {predicted} для {method}(), а записей "
                    f"{len(written)}: таблица _LEVEL_DEFAULT_SCOPE разошлась с методом"
                )
                assert _LEVEL_DEFAULT_SCOPE[level] is not None
        finally:
            mgr.shutdown()

    def test_the_scope_argument_no_longer_changes_the_verdict(self, logger: Any) -> None:
        """Ф8.1: скоуп на решение гейта не влияет — и это проверяется, а не подразумевается.

        Прежний тест на этом месте утверждал обратное («у SYSTEM порог WARNING, у
        BUSINESS — INFO, предикат обязан их различать»). Различие исчезло вместе
        со второй осью, и молчаливо этого оставлять нельзя: ``is_enabled_for``
        по-прежнему ПРИНИМАЕТ ``scope``, потому что аргумент нужен маршруту,
        и без теста читатель сигнатуры решил бы, что он ещё и фильтрует.

        Пара «два разных скоупа — один ответ» плюс «порог правила ответ меняет»:
        первое без второго зелено и у гейта, который просто всегда говорит True.
        """
        assert logger.is_enabled_for("main", LogLevel.INFO, LogScope.SYSTEM) is True
        assert logger.is_enabled_for("main", LogLevel.INFO, LogScope.BUSINESS) is True
        assert logger.is_enabled_for("main", LogLevel.DEBUG, LogScope.SYSTEM) is False
        assert logger.is_enabled_for("main", LogLevel.DEBUG, LogScope.BUSINESS) is False


# =============================================================================
# Характеризация: whitelist `modules` после штампа Ф2.1 (находка ревью Н1)
# =============================================================================


class _StampedManager(BaseManager, ObservableMixin):
    """Менеджер, чьи записи после Ф2.1 едут под собственным именем."""

    def __init__(self, name: str, logger: Any) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={"logger": logger})

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


def _rule_logger(tmp_path: Path, rules: Dict[str, dict]) -> LoggerManager:
    """Логгер, адресующий источники ПРАВИЛАМИ ИМЁН (Ф8.1: whitelist `modules` снят).

    Корень поднят до CRITICAL, чтобы «прошло» означало «прошло по правилу», а не
    «прошло, потому что и так всё открыто»: без глухого корня тест был бы зелёным
    при полностью выключенном резолве.
    """
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="wl",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"f": LoggerChannelSchema(name="f", type="file", enabled=True, file_path="s.log", rotate=False)},
            default_level="CRITICAL",
            scopes={scope: LoggerScopeSchema(channels=["f"]) for scope in ("SYSTEM", "BUSINESS", "DEBUG")},
            loggers={имя: LoggerRuleSchema.model_validate(правило) for имя, правило in rules.items()},
        )
    )


class TestPrefixRuleReplacedTheWhitelist:
    """Ф8.1 (Р-2.4-Г): whitelist ``modules`` снят, адресация — правилом по префиксу.

    Класс заменил ``TestWhitelistSemanticsAfterStamping``. Тот прямо предсказывал
    эту замену: *«если иерархия имён решит, что whitelist должен понимать префиксы,
    эти тесты покраснеют, и это будет правильный сигнал — семантику меняем
    осознанно»*. Они покраснели; смена осознанная и записана здесь.

    Что осталось прежним: проверка идёт **по файлу**, а не по счётчику. Счётчик
    «отклонено гейтом» сказал бы то же самое и при исправной доставке.

    Что изменилось по существу: whitelist сравнивал имя строго по равенству, и
    третий тест ниже раньше проверял именно это ограничение. Теперь он проверяет
    обратное — и в этом весь смысл перехода: правило родителя действует на
    потомков, поэтому источник, которого ещё нет, конфига не требует.
    """

    def test_the_stamped_name_is_what_the_rule_addresses(self, tmp_path: Path) -> None:
        """Правило по настоящему имени источника запись пропускает.

        Ф2.1 штампует записи менеджеров их именем (``router_manager``), а не
        ``main``, — правило адресует именно его.
        """
        logger = _rule_logger(tmp_path, {"router_manager": {"level": "DEBUG"}})
        try:
            _StampedManager("router_manager", logger)._log_info("запись менеджера")
        finally:
            logger.shutdown()

        assert "запись менеджера" in (tmp_path / "s.log").read_text(encoding="utf-8")

    def test_a_rule_for_someone_else_does_not_let_it_through(self, tmp_path: Path) -> None:
        """Обратная половина: чужое правило запись не пропускает.

        Без неё первый тест зелен и при правиле, которое пропускает вообще всё.
        """
        logger = _rule_logger(tmp_path, {"кто_то_другой": {"level": "DEBUG"}})
        try:
            _StampedManager("router_manager", logger)._log_info("запись менеджера")
        finally:
            logger.shutdown()

        assert "запись менеджера" not in (tmp_path / "s.log").read_text(encoding="utf-8")

    def test_the_rule_now_reaches_descendants_which_the_whitelist_could_not(self, tmp_path: Path) -> None:
        """**Смена семантики, названная вслух.** Правило поддерева ловит потомка.

        Прежний тест на этом месте утверждал ОБРАТНОЕ: whitelist ``["router"]``
        запись источника ``router.manager`` не пропускал, потому что сравнение
        шло по равенству. Ради этого свойства фаза и делалась — новый плагин
        поддерева подчиняется правилу родителя, и конфиг при его добавлении не
        трогают.

        Совпадение по ГРАНИЦЕ ТОЧКИ, а не по началу строки: пара ниже стережёт
        ровно это — ``router`` не должен ловить ``routerX``, иначе источник молча
        получил бы чужой порог.
        """
        logger = _rule_logger(tmp_path, {"router": {"level": "DEBUG"}})
        try:
            _StampedManager("router.manager", logger)._log_info("запись потомка")
            _StampedManager("routerX", logger)._log_info("запись однофамильца")
        finally:
            logger.shutdown()

        text = (tmp_path / "s.log").read_text(encoding="utf-8")
        assert "запись потомка" in text, "правило родителя обязано действовать на поддерево"
        assert "запись однофамильца" not in text, "совпадение только по границе точки, а не по началу строки"
