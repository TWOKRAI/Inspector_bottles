# -*- coding: utf-8 -*-
"""Task 2.3 (находка Н-7): менеджеры процесса РОЖДАЮТСЯ с конфигом, а не чинятся после.

**Что было.** Секция ``managers`` приезжает готовой только тем процессам, которых
собирал ассемблер. Оркестратор спавнится другим кодом, и ключа в его bundle нет
вовсе — его менеджеры создавались на дефолтах L0. Первым, что делал ``StatsManager``
оркестратора на КАЖДОМ старте, было предупреждение о собственном конфиге::

    [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола
    stats.flush_interval=10.0 — действует 10.0 с.

…при том что ``system.yaml`` задавал ``aggregation_interval: 10.0``, и дети того же
стенда молчали. Предупреждение было правдой про менеджер и ложью про систему:
значения доносила пересборка ``_apply_boot_observability_layers`` секундой позже.

**Почему это не «просто шум» — и почему находка числила «не действует» НЕ доказанным.**
Разведка (2026-08-11) прогнала расходящуюся пару и показала, где прячется разница:

======================== ================= ==================== ==============
Что                      Задано в yaml     ПМ при создании      Совпало?
======================== ================= ==================== ==============
``aggregation_interval`` 10.0              5.0 → readback 10.0  **да**, потому
                                                                что темп это
                                                                ``max(flush, agg)``
                                                                и ``max(5,10) ==
                                                                max(10,10)``
``flush_interval``       2.0               **10.0**             нет, впятеро
======================== ================= ==================== ==============

То есть проверяй мы ту ручку, о которой предупреждение, — вывод был бы «всё в
порядке». Различает ветки только сосед, и только на паре, где они расходятся.

**Граница.** Здесь судится РОЖДЕНИЕ менеджеров. Пересборка на boot никуда не делась
и закрывает вторую ветку — спутник рецепта, которого на момент создания ещё не
читали; её пара тестов живёт в ``test_observability_boot_layers.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import APP_CONFIG_KEY
from multiprocess_framework.modules.process_module.managers.process_managers import ProcessManagers
from multiprocess_framework.modules.statistics_module import StatsManager, StatsManagerConfig

#: Пара, на которой ветки РАСХОДЯТСЯ. Числа подобраны не для красоты: при дефолтах
#: (agg=5.0, flush=10.0) действующий темп ``max`` совпадает с заданным, и только
#: ``flush_interval`` показывает, доехал конфиг или нет.
DIVERGING = {"aggregation_interval": 10.0, "flush_interval": 2.0}


class _Handler:
    """Секция менеджеров в том виде, в каком её отдаёт настоящий handler."""

    def __init__(self, managers: Optional[Dict[str, Any]]) -> None:
        self._managers = managers

    def get_managers_config(self) -> Dict[str, Any]:
        return self._managers or {}


class _Proc:
    """Процесс в форме ОРКЕСТРАТОРА: spawner мержит конфиг в корень, без ``config.``."""

    def __init__(self, name: str, flat: Dict[str, Any], handler: _Handler) -> None:
        self.name = name
        self.config_handler = handler
        self.config_manager = None
        self._flat = flat

    def get_config(self, key: str, default: Any = None) -> Any:
        node: Any = self._flat
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class _CapturingLogger:
    """Логгер, который ЗАПОМИНАЕТ предупреждения: приёмка 2.3 — их число."""

    def __init__(self) -> None:
        self.warnings: List[str] = []

    def warning(self, message: Any, **kw: Any) -> None:
        self.warnings.append(str(message))

    def log_warning(self, message: Any, **kw: Any) -> None:
        self.warnings.append(str(message))

    def info(self, *a: Any, **k: Any) -> None: ...
    def debug(self, *a: Any, **k: Any) -> None: ...
    def error(self, *a: Any, **k: Any) -> None: ...


def _orchestrator(section: Optional[Dict[str, Any]] = None, *, managers: Optional[Dict[str, Any]] = None) -> _Proc:
    flat = {APP_CONFIG_KEY: {"log_level": "WARNING", "stats": dict(section)}} if section else {}
    return _Proc("ProcessManager", flat, _Handler(managers))


def _stats_from(section: Dict[str, Any], process: _Proc, logger: _CapturingLogger) -> StatsManager:
    """Создать StatsManager ровно так, как это делает ``_create_stats_manager``."""
    stats_config = StatsManagerConfig()
    for key, value in (section.get("stats") or {}).items():
        if hasattr(stats_config, key):
            setattr(stats_config, key, value)
    stats = StatsManager(
        manager_name=f"stats_{process.name}",
        config=stats_config,
        process=process,
        managers={"logger": logger},
    )
    stats.initialize()
    return stats


class TestTheDivergingMeasurement:
    """Различающий замер: пара, где «доехало» и «дефолты» дают РАЗНЫЕ числа."""

    def test_the_pair_really_diverges(self) -> None:
        """Контроль метода: числа взяты там, где ветки расходятся.

        Без этого теста вся пачка ниже могла бы стоять на паре, где дефолт и
        конфиг совпадают, — и была бы зелёной при полностью несработавшем
        механизме. Дефолты берутся из схемы, а не переписываются литералом:
        второй источник разошёлся бы молча.
        """
        defaults = StatsManagerConfig()
        assert defaults.flush_interval != DIVERGING["flush_interval"], "пол совпал с дефолтом — замер не различает"
        # А вот действующий ТЕМП совпадает — и это то, что прятало дефект:
        assert max(defaults.flush_interval, defaults.aggregation_interval) == max(
            DIVERGING["flush_interval"], DIVERGING["aggregation_interval"]
        ), "предпосылка находки исчезла: темп больше не совпадает, проверьте дефолты схемы"

    def test_orchestrator_is_born_with_the_yaml_values(self) -> None:
        """Главная пара 2.3: пустая секция + непустые слои → конфиг из yaml."""
        proc = _orchestrator(DIVERGING)
        section = ProcessManagers(proc)._managers_config_for_creation()
        assert section["stats"]["flush_interval"] == 2.0
        assert section["stats"]["aggregation_interval"] == 10.0

    def test_the_floor_reaches_the_live_manager(self) -> None:
        """Не «секция посчиталась», а «менеджер живёт по ней» — readback из живого окна."""
        proc = _orchestrator(DIVERGING)
        logger = _CapturingLogger()
        stats = _stats_from(ProcessManagers(proc)._managers_config_for_creation(), proc, logger)
        try:
            readback = stats.observability_readback()
            assert readback["flush_interval"] == 2.0
            assert readback["aggregation_interval"] == 10.0
        finally:
            stats.shutdown()

    def test_boot_says_nothing_when_the_config_arrived(self) -> None:
        """Приёмка 2.3 дословно: ноль предупреждений на старте оркестратора."""
        proc = _orchestrator(DIVERGING)
        logger = _CapturingLogger()
        stats = _stats_from(ProcessManagers(proc)._managers_config_for_creation(), proc, logger)
        try:
            assert logger.warnings == [], f"старт снова говорит о своём конфиге: {logger.warnings}"
        finally:
            stats.shutdown()

    def test_the_warning_is_alive_and_addressed_when_it_should_fire(self) -> None:
        """Пара к предыдущему: детектор, срабатывающий никогда, ничего не значит.

        Настоящее нарушение пола обязано быть громким и НАЗЫВАТЬ ключ — иначе
        «0 предупреждений» доказывало бы заглушенный логгер, а не доехавший конфиг.
        """
        proc = _orchestrator({"aggregation_interval": 1.0, "flush_interval": 30.0})
        logger = _CapturingLogger()
        stats = _stats_from(ProcessManagers(proc)._managers_config_for_creation(), proc, logger)
        try:
            assert len(logger.warnings) == 1
            assert "stats.aggregation_interval" in logger.warnings[0]
            assert "stats.flush_interval" in logger.warnings[0]
        finally:
            stats.shutdown()


class TestWhoOwnsTheSection:
    """Кто чей конфиг переписывает — граница, а не вкус."""

    def test_a_ready_section_wins_over_the_layers(self) -> None:
        """Ребёнок пришёл со своей секцией — слои её здесь НЕ трогают.

        Раскладку слоёв в секцию делает ассемблер, и делать её второй раз здесь
        значило бы завести два источника одной секции. Проверяется числом: слои
        говорят 2.0, секция — 7.0, побеждает секция.
        """
        proc = _Proc(
            "camera_0",
            {APP_CONFIG_KEY: {"stats": dict(DIVERGING)}},
            _Handler({"stats": {"flush_interval": 7.0}}),
        )
        section = ProcessManagers(proc)._managers_config_for_creation()
        assert section["stats"]["flush_interval"] == 7.0

    def test_silent_layers_leave_the_empty_section_empty(self) -> None:
        """Молчащие слои не дают повода подставлять дефолты L0.

        ``expand_observability({})`` — не пустота, а ПОЛНЫЙ набор дефолтов.
        Подставь мы его встройщику, собравшему менеджеры программно, — его
        настройка была бы тихо отменена. Тот же инвариант, что у пересборки
        на boot (``layers_are_silent``).
        """
        proc = _Proc("embedded", {}, _Handler({}))
        assert ProcessManagers(proc)._managers_config_for_creation() == {}

    def test_the_criterion_is_structural_not_the_name(self) -> None:
        """Признак — «секция пуста», а не «имя == ProcessManager».

        Починка по имени закрыла бы одного адресата и оставила бы дефект ждать
        следующего процесса, поднятого без готовой секции. Здесь имя чужое.
        """
        proc = _Proc("своя_сборка_без_ассемблера", {APP_CONFIG_KEY: {"stats": dict(DIVERGING)}}, _Handler({}))
        section = ProcessManagers(proc)._managers_config_for_creation()
        assert section["stats"]["flush_interval"] == 2.0


class TestNeighbourPlanesOfTheSameBirth:
    """Дефект был у stats, но рождались на дефолтах ВСЕ менеджеры процесса."""

    @pytest.mark.parametrize(
        "plane,key,value",
        [
            ("logger", "default_level", "WARNING"),
            # У плоскости ошибок ключ секции — `errors.level`, а ключ МЕНЕДЖЕРА —
            # `default_level`: раскладка переименовывает его. Имя взято из
            # `expand_observability`, а не из секции конфига — иначе тест судил бы
            # написание в yaml, а не то, что доехало до менеджера.
            ("error", "default_level", "ERROR"),
        ],
    )
    def test_other_planes_are_born_configured_too(self, plane, key, value) -> None:
        """Соседи по секции обязаны приезжать той же дорогой — иначе починен один путь из трёх."""
        proc = _Proc(
            "ProcessManager",
            {APP_CONFIG_KEY: {"log_level": "WARNING", "errors": {"level": "ERROR"}}},
            _Handler({}),
        )
        section = ProcessManagers(proc)._managers_config_for_creation()
        assert section[plane][key] == value
