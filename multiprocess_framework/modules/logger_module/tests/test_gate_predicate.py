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
from multiprocess_framework.modules.logger_module.core.logger_core import _LEVEL_DEFAULT_SCOPE
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


class TestScopeGateCharacterization:
    """Поведение ``LoggerScopeSchema.should_log`` — снято с прежней реализации."""

    def test_below_threshold_is_rejected(self) -> None:
        scope = LoggerScopeSchema(enabled=True, min_level="WARNING")
        assert scope.should_log(LogLevel.INFO, "any") is False
        assert scope.should_log(LogLevel.WARNING, "any") is True
        assert scope.should_log(LogLevel.CRITICAL, "any") is True

    def test_disabled_scope_rejects_everything(self) -> None:
        scope = LoggerScopeSchema(enabled=False, min_level="DEBUG")
        assert scope.should_log(LogLevel.CRITICAL, "any") is False

    def test_module_filter_applies_above_threshold(self) -> None:
        scope = LoggerScopeSchema(enabled=True, min_level="DEBUG", modules=["camera"])
        assert scope.should_log(LogLevel.INFO, "camera") is True
        assert scope.should_log(LogLevel.INFO, "gui") is False

    def test_lowercase_min_level_still_works(self) -> None:
        """``min_level`` нормализуется — прежняя реализация звала ``.upper()``."""
        scope = LoggerScopeSchema(enabled=True, min_level="warning")
        assert scope.should_log(LogLevel.INFO, "any") is False
        assert scope.should_log(LogLevel.ERROR, "any") is True

    def test_unknown_min_level_is_refused_at_the_boundary(self) -> None:
        """Ф3.1: незнакомый порог до гейта больше НЕ доезжает.

        Прежде здесь была характеризация странности: ``ValueError`` из
        ``index()`` возвращал ``True`` ДО проверки модулей, то есть незнакомый
        порог отключал заодно и фильтр модулей. Странность была сохранена
        осознанно — её нельзя было менять попутно с оптимизацией Ф1.1.

        Теперь её чинит отдельная задача, и чинит на входе: имя проверяется в
        валидаторе схемы. Сам гейт по-прежнему fail-open (проверяется ниже
        через ``model_construct``, обходящий валидацию) — это последний рубеж
        для программного вызова, а не первый.
        """
        import pytest as _pytest

        with _pytest.raises(ValueError, match="неизвестный уровень"):
            LoggerScopeSchema(enabled=True, min_level="ОПЕЧАТКА", modules=["camera"])

    def test_gate_stays_fail_open_when_validation_is_bypassed(self) -> None:
        """Рубеж горячего пути: минуя валидацию, незнакомый порог пропускает всё.

        Fail-closed здесь означал бы тишину от опечатки — невидимую потерю,
        запрещённую инвариантом 2 плана. Фильтр модулей тоже отключается, как
        и прежде: это ровно та же ветка.
        """
        scope = LoggerScopeSchema.model_construct(enabled=True, min_level="ОПЕЧАТКА", modules=["camera"])
        assert scope.should_log(LogLevel.DEBUG, "gui") is True

    def test_precomputed_threshold_follows_field_assignment(self) -> None:
        """Слепок не может разъехаться с полем: присваивание пересчитывает его.

        Без этого правка ``min_level`` у живой схемы оставила бы гейт на старом
        пороге — дефект, который в проде выглядел бы как «конфиг применили, а
        уровень не поменялся».
        """
        scope = LoggerScopeSchema(enabled=True, min_level="DEBUG")
        assert scope.should_log(LogLevel.INFO, "any") is True

        scope.min_level = "ERROR"
        assert scope.should_log(LogLevel.INFO, "any") is False
        assert scope.should_log(LogLevel.ERROR, "any") is True

    def test_module_filter_follows_field_assignment(self) -> None:
        scope = LoggerScopeSchema(enabled=True, min_level="DEBUG")
        assert scope.should_log(LogLevel.INFO, "gui") is True

        scope.modules = ["camera"]
        assert scope.should_log(LogLevel.INFO, "gui") is False
        assert scope.should_log(LogLevel.INFO, "camera") is True


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
                "scopes": {
                    "SYSTEM": {"enabled": True, "min_level": "WARNING", "channels": ["probe"]},
                    "BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["probe"]},
                    "DEBUG": {"enabled": True, "min_level": "DEBUG", "channels": ["probe"]},
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

    def test_explicit_scope_overrides_default(self, logger: Any) -> None:
        """У SYSTEM порог WARNING, у BUSINESS — INFO; предикат обязан их различать."""
        assert logger.is_enabled_for("main", LogLevel.INFO, LogScope.SYSTEM) is False
        assert logger.is_enabled_for("main", LogLevel.INFO, LogScope.BUSINESS) is True


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


def _whitelist_logger(tmp_path: Path, allowed: List[str]) -> LoggerManager:
    """Логгер, у которого каждый scope пускает ТОЛЬКО перечисленные модули."""
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="wl",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"f": LoggerChannelSchema(name="f", type="file", enabled=True, file_path="s.log", rotate=False)},
            scopes={
                scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["f"], modules=list(allowed))
                for scope in ("SYSTEM", "BUSINESS", "DEBUG")
            },
        )
    )


class TestWhitelistSemanticsAfterStamping:
    """Ф2.1 сменила смысл поля `modules` в scope — и это надо было назвать вслух.

    До штампа записи менеджеров приходили под ``module="main"`` и проходили
    любой whitelist, где есть ``"main"``. После штампа они приходят под своим
    именем — и тот же самый конфиг их глушит. Ни один конфиг репозитория
    whitelist сегодня не задаёт, поэтому дефекта в проде нет; но это смена
    семантики конфига, и она обязана быть закреплена тестом, а не памятью.

    Тесты снимают ПОВЕДЕНИЕ как есть. Если 2.2 (иерархия имён) решит, что
    whitelist должен понимать префиксы — эти тесты покраснеют, и это будет
    правильный сигнал «семантику меняем осознанно», а не тихий дрейф.

    Проверка идёт по ФАЙЛУ, а не по счётчику: счётчик «отклонено гейтом»
    сказал бы то же самое и при исправной доставке.
    """

    def test_stamped_record_is_dropped_by_main_only_whitelist(self, tmp_path: Path) -> None:
        """Воспроизведение находки: whitelist ["main"] глушит менеджерскую запись."""
        logger = _whitelist_logger(tmp_path, allowed=["main"])
        try:
            logger.info("прямой вызов без миксина")
            _StampedManager("router_manager", logger)._log_info("запись менеджера")
        finally:
            logger.shutdown()

        text = (tmp_path / "s.log").read_text(encoding="utf-8")
        assert "прямой вызов без миксина" in text, "запись под 'main' обязана пройти whitelist"
        assert "запись менеджера" not in text, (
            "характеризация: после Ф2.1 запись едет под 'router_manager' и whitelist "
            "['main'] её отсекает — если это изменилось, семантику поменяли осознанно"
        )

    def test_whitelist_with_real_source_name_lets_record_through(self, tmp_path: Path) -> None:
        """Обратная сторона: whitelist, знающий настоящее имя, запись пропускает.

        Без этой половины первый тест зелен и при полностью сломанной записи.
        """
        logger = _whitelist_logger(tmp_path, allowed=["router_manager"])
        try:
            _StampedManager("router_manager", logger)._log_info("запись менеджера")
        finally:
            logger.shutdown()

        assert "запись менеджера" in (tmp_path / "s.log").read_text(encoding="utf-8")

    def test_whitelist_does_not_match_by_prefix_today(self, tmp_path: Path) -> None:
        """Сегодня сравнение строгое по равенству — префикса ('router') мало.

        Это и есть точка входа задачи 2.2: иерархия по точкам должна будет
        решить, распространяется ли правило родителя на потомков.
        """
        logger = _whitelist_logger(tmp_path, allowed=["router"])
        try:
            _StampedManager("router_manager", logger)._log_info("запись менеджера")
        finally:
            logger.shutdown()

        assert "запись менеджера" not in (tmp_path / "s.log").read_text(encoding="utf-8")
