# -*- coding: utf-8 -*-
"""R9, второй рубеж на боевом менеджере: сбой пересборки откатывается.

Механику отката проверяют тесты базы (`channel_routing_module/tests/
test_reconfigure_validate_then_swap.py`) на модельном наследнике. Здесь — то,
чего модель не покрывает: у LoggerCore свой конструктор, и он передаёт в базу
``config=None`` (конфиг логгер резолвит сам). Слепок для отката база в этом
случае выставить не может — и второй рубеж оказывается мёртвым именно у двух
менеджеров, ради которых он делался.

Найдено слом-инъекцией B1 (снять валидацию → у логгера и ошибок реестр остаётся
ПУСТЫМ, хотя откат обязан был сработать), а не чтением: по коду базы всё
выглядело исправно.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


def _logger(tmp_path: Path) -> LoggerManager:
    mgr = LoggerManager(
        manager_name="R9Rollback",
        config=LoggerManagerConfig(
            app_name="r9_rollback",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "system_file": LoggerChannelSchema(
                    name="system_file",
                    type="file",
                    enabled=True,
                    file_path="system.log",
                    format="%(message)s",
                    rotate=False,
                ),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])},
        ),
    )
    mgr.initialize()
    return mgr


def test_rollback_snapshot_is_set_at_construction(tmp_path: Path) -> None:
    """Слепок для отката существует сразу после создания менеджера.

    Прямая проверка предусловия: без неё функциональный тест ниже мог бы
    зеленеть по случайной причине, а сам дефект (слепок = None) невидим.
    """
    mgr = _logger(tmp_path)
    try:
        assert mgr._last_applied_config is not None, "откатываться не к чему: второй рубеж мёртв"
    finally:
        mgr.shutdown()


def test_rebuild_failure_restores_channels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Конфиг валиден, но пересборка развалилась → каналы возвращаются, логгер пишет.

    Отказ ОС при открытии файла, гонка за путь, битые права — валидация такого
    не ловит принципиально: конфиг корректен, ломается применение.
    """
    mgr = _logger(tmp_path)
    try:
        before = sorted(mgr._channel_registry.names())
        assert before == ["system_file"]

        calls = {"n": 0}
        original = mgr._setup_channels

        def _explode_once() -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("не смог открыть файл канала")
            original()

        monkeypatch.setattr(mgr, "_setup_channels", _explode_once)

        raw = mgr.config.model_dump()
        raw["app_name"] = "переименованный"
        assert mgr.reconfigure(raw) is False, "сбой пересборки обязан быть отказом"

        assert sorted(mgr._channel_registry.names()) == before, "откат не вернул каналы"
        assert calls["n"] >= 2, "откат не пересобирал каналы вовсе"

        mgr.error("после отката логгер обязан писать", module="r9")
        mgr.flush()
        assert "после отката" in (tmp_path / "system.log").read_text(encoding="utf-8", errors="replace")
    finally:
        mgr.shutdown()


def test_rejected_config_does_not_touch_channels(tmp_path: Path) -> None:
    """Первый рубеж отличим от второго: отвергнутый конфиг не ЗАКРЫВАЕТ каналы.

    Без этой проверки «реестр цел» доказывало бы только то, что цел ОДИН из двух
    рубежей: откат воссоздаёт каналы с теми же именами, и по именам два исхода
    неразличимы. Здесь сравниваются объекты — пересозданный каналом не является.
    """
    mgr = _logger(tmp_path)
    try:
        channel_before = mgr._channel_registry.get("system_file")

        raw = mgr.config.model_dump()
        raw["sampling_max_level"] = "ЖЁЛТЫЙ"  # Ф7.4: прежнее негодное поле снято вместе с батчингом
        assert mgr.reconfigure(raw) is False

        assert mgr._channel_registry.get("system_file") is channel_before, (
            "канал пересоздан: конфиг был отвергнут ПОСЛЕ разрушения, спас только откат"
        )
    finally:
        mgr.shutdown()
