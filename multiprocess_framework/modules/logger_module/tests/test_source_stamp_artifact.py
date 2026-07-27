# -*- coding: utf-8 -*-
"""Ф2.1 — имя источника доезжает ДО ФАЙЛА, а не только до слота.

План: plans/observability-unified-routing.md, задача 2.1.

Зачем отдельно от ``base_manager/tests/test_source_stamping.py``. Тот файл
проверяет, что миксин передал ``module=`` в слот. Этого мало: между слотом и
диском лежат гейт, роутинг, батч-буфер и ``logging.Formatter``, и любая из
ступеней могла бы имя потерять. Приёмка задачи 2.1 сформулирована на артефакте
(«записи трёх разных модулей различимы по имени»), поэтому и проверка — по
байтам в файле.

Второй сквозной путь — worker'ский: запись едет ``ObservableMixin →
ObservabilityHub → drain → LoggerManager → файл``. Он длиннее прямого, и на нём
имя источника хранится не в поле записи, а в её ``context`` — то есть ломается
он независимо от прямого пути.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, List

import pytest

from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.modules.channel_routing_module.observability.drain_adapter import (
    ObservabilityDrainAdapter,
)
from multiprocess_framework.modules.channel_routing_module.observability.observability_hub import (
    ObservabilityHub,
)
from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    reset_error_floors()
    yield
    reset_error_floors()


def _config(tmp_path: Path) -> LoggerManagerConfig:
    """Один файловый канал, без батчинга: запись ложится на диск сразу."""
    return LoggerManagerConfig(
        app_name="stamp_artifact",
        log_directory=str(tmp_path),
        enable_batching=False,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file",
                type="file",
                enabled=True,
                file_path="system.log",
                rotate=False,
            )
        },
        scopes={
            scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])
            for scope in ("SYSTEM", "BUSINESS", "DEBUG")
        },
    )


class _Manager(BaseManager, ObservableMixin):
    def __init__(self, name: str, logger: Any) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={"logger": logger})

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


def _lines(tmp_path: Path) -> List[str]:
    return (tmp_path / "system.log").read_text(encoding="utf-8").splitlines()


def _name_field(line: str) -> str:
    """Вытащить ``%(name)s`` из формата ``asctime [LEVEL] name: message``.

    Разбор буквальный, по разделителям формата, а не по регуляркe вокруг
    ожидаемого имени: иначе тест согласился бы с любым именем, которое сам же
    и подставил.
    """
    after_level = line.split("] ", 1)[1]
    return after_level.split(": ", 1)[0]


def test_three_managers_are_distinguishable_in_the_file(tmp_path: Path) -> None:
    """Приёмка 2.1: три менеджера — три разных имени в артефакте."""
    logger = LoggerManager(config=_config(tmp_path))
    try:
        _Manager("capture_manager", logger)._log_info("кадр получен")
        _Manager("router_manager", logger)._log_info("сообщение доставлено")
        _Manager("state_manager", logger)._log_info("дерево обновлено")
    finally:
        logger.shutdown()

    names = [_name_field(line) for line in _lines(tmp_path)]
    # Хвост — служебные записи самого логгера при shutdown; они тоже штампованы
    # (``logger_manager``), поэтому сравниваем первые три, а не весь файл.
    assert names[:3] == ["capture_manager", "router_manager", "state_manager"]


def test_default_main_no_longer_hides_instrumented_managers(tmp_path: Path) -> None:
    """До Ф2.1 все три строки выше легли бы под ``main``. Проверяем именно
    отсутствие дефолта, а не наличие имён: это две разные поломки."""
    logger = LoggerManager(config=_config(tmp_path))
    try:
        _Manager("capture_manager", logger)._log_info("кадр получен")
    finally:
        logger.shutdown()

    assert _name_field(_lines(tmp_path)[0]) != "main"


def test_direct_logger_call_keeps_its_default(tmp_path: Path) -> None:
    """Прямой вызов логгера мимо миксина остаётся с дефолтом ``main`` —
    штамп не подменяет чужое поведение, он добавляет своё."""
    logger = LoggerManager(config=_config(tmp_path))
    try:
        logger.info("напрямую, без миксина")
    finally:
        logger.shutdown()

    assert _name_field(_lines(tmp_path)[0]) == "main"


def test_hub_drain_path_preserves_source_name(tmp_path: Path) -> None:
    """Worker'ский путь: миксин → hub → drain → logger → файл.

    Имя источника на этом маршруте живёт в ``context`` записи hub'а, а не в её
    поле ``module`` (там hub держит собственный тег). Если drain перестанет
    прокидывать контекст keyword'ами, имя молча заменится на ``main``.
    """
    logger = LoggerManager(config=_config(tmp_path))
    hub = ObservabilityHub("worker_module", capacity=64)
    try:
        _Manager("pool_dispatcher", hub)._log_info("задача взята")
        ObservabilityDrainAdapter(logger=logger).apply_drained(hub.drain_all())
    finally:
        logger.shutdown()

    assert _name_field(_lines(tmp_path)[0]) == "pool_dispatcher"


def test_hub_keeps_its_own_module_tag(tmp_path: Path) -> None:
    """Обратная сторона предыдущего: собственный тег hub'а не подменяется
    именем источника — записи hub'а по-прежнему группируются по владельцу."""
    hub = ObservabilityHub("worker_module", capacity=64)
    _Manager("pool_dispatcher", hub)._log_info("задача взята")

    record = hub.drain_all()["log"][0]
    assert record["module"] == "worker_module"
    assert record["context"]["module"] == "pool_dispatcher"
