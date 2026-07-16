# -*- coding: utf-8 -*-
"""Характеризация hot-swap gap fix (PC 3.1).

Пробел (PC 1.3 «Известный пробел»): ``configure_topology_engine`` строил
``BlueprintAssembler`` БЕЗ ``telemetry_dict`` → глобальный дефолт ``telemetry.publish``
из ``system.yaml`` не доезжал до процессов, ПЕРЕСОБРАННЫХ при hot-swap рецепта.

Фикс: hook прокидывает ``sys_config.telemetry.publish.model_dump()`` в assembler —
как boot (``launch.py``). Тест перехватывает конструктор ``BlueprintAssembler`` и
проверяет переданный ``telemetry_dict`` (планировщик тоже застаблен — не поднимаем
реальный движок).
"""

from __future__ import annotations

from typing import Any

import multiprocess_prototype.backend.assembly as assembly_pkg
from multiprocess_prototype.backend.config.schemas import SystemConfig
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine


class _CaptureAssembler:
    """Перехват конструктора BlueprintAssembler — фиксирует kwargs, assemble → {}."""

    last: dict = {}

    def __init__(self, observability_dict: Any, log_dir: str = "logs", telemetry_dict: Any = None) -> None:
        _CaptureAssembler.last = {
            "observability_dict": observability_dict,
            "log_dir": log_dir,
            "telemetry_dict": telemetry_dict,
        }

    def assemble(self, blueprint_dict: dict) -> dict:
        return {}


class _StubPlanner:
    """Застабленный FullReplacePlanner — не поднимает реальный движок."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def initialize(self) -> None: ...
    def diff(self, *a: Any, **k: Any) -> Any: ...
    def commands(self, *a: Any, **k: Any) -> Any: ...


class _StubTopologyManager:
    def __init__(self) -> None:
        self.configured: dict = {}

    def configure(self, *, diff_fn, commands_fn) -> None:
        self.configured = {"diff_fn": diff_fn, "commands_fn": commands_fn}


class _StubOrchestrator:
    """Минимальный оркестратор для configure_topology_engine (duck-typed)."""

    def __init__(self, sys_config_dict: dict) -> None:
        self._sys_config_dict = sys_config_dict
        self._topology_manager = _StubTopologyManager()
        self._full_replace_planner = None
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._sys_config_dict if key == "sys_config" else default

    def _log_info(self, *a: Any, **k: Any) -> None: ...

    # Провайдеры для планировщика (застаблены — не вызываются в тесте).
    def _get_protected_names(self) -> list: ...
    def _topology_current_names(self) -> list: ...
    def live_process_config(self, name: str) -> dict: ...


def _patch_engine(monkeypatch) -> None:
    """Подменить тяжёлые символы, резолвимые ВНУТРИ хука (lazy-импорт из assembly)."""
    monkeypatch.setattr(assembly_pkg, "BlueprintAssembler", _CaptureAssembler)
    monkeypatch.setattr(assembly_pkg, "FullReplacePlanner", _StubPlanner)
    _CaptureAssembler.last = {}


def test_hot_swap_forwards_global_telemetry(monkeypatch) -> None:
    """Глобальный telemetry.publish → assembler hot-swap получает его как telemetry_dict."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate(
        {
            "discovery": {"auto_discover": False},  # пропустить discover в тесте
            "telemetry": {"publish": {"default_interval_sec": 2.0, "metrics": {"fps": {"enabled": False}}}},
        }
    )
    orch = _StubOrchestrator(sys_config.model_dump())

    configure_topology_engine(orch)

    expected = sys_config.telemetry.publish.model_dump()
    assert _CaptureAssembler.last["telemetry_dict"] == expected
    assert _CaptureAssembler.last["telemetry_dict"]["metrics"]["fps"]["enabled"] is False


def test_hot_swap_no_telemetry_passes_none(monkeypatch) -> None:
    """Нет глобальной telemetry.publish → telemetry_dict=None (backward-compat)."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    orch = _StubOrchestrator(sys_config.model_dump())

    configure_topology_engine(orch)

    assert _CaptureAssembler.last["telemetry_dict"] is None


def test_hot_swap_configures_topology_manager(monkeypatch) -> None:
    """Sanity: хук всё ещё конфигурирует TopologyManager (diff/commands из планировщика)."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    orch = _StubOrchestrator(sys_config.model_dump())

    configure_topology_engine(orch)

    assert orch._topology_manager.configured.get("diff_fn") is not None
    assert orch._topology_manager.configured.get("commands_fn") is not None
    assert orch._full_replace_planner is not None
