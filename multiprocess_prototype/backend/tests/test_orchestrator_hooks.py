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

    def __init__(
        self,
        observability_section: Any,
        log_dir: str = "logs",
        telemetry_dict: Any = None,
        recipe_path: str = "",
        app_config_path: str = "",
    ) -> None:
        _CaptureAssembler.last = {
            "observability_section": observability_section,
            "log_dir": log_dir,
            "telemetry_dict": telemetry_dict,
            "recipe_path": recipe_path,
            "app_config_path": app_config_path,
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

    def __init__(self, sys_config_dict: dict, extra_config: dict | None = None) -> None:
        self._sys_config_dict = sys_config_dict
        self._extra_config = dict(extra_config or {})
        self._topology_manager = _StubTopologyManager()
        self._full_replace_planner = None
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None

    def get_config(self, key: str, default: Any = None) -> Any:
        if key == "sys_config":
            return self._sys_config_dict
        return self._extra_config.get(key, default)

    def _log_info(self, *a: Any, **k: Any) -> None: ...

    def _log_error(self, *a: Any, **k: Any) -> None: ...

    # Провайдеры для планировщика (застаблены — не вызываются в тесте).
    def _get_protected_names(self) -> list: ...
    def _topology_current_names(self) -> list: ...
    def live_process_config(self, name: str) -> dict: ...


def _patch_engine(monkeypatch) -> None:
    """Подменить тяжёлые символы, резолвимые ВНУТРИ хука (lazy-импорт из assembly)."""
    monkeypatch.setattr(assembly_pkg, "BlueprintAssembler", _CaptureAssembler)
    monkeypatch.setattr(assembly_pkg, "FullReplacePlanner", _StubPlanner)
    _CaptureAssembler.last = {}


def _build(orch) -> None:
    """Дёрнуть реальную сборку proc_dict'ов (Task 5.12: ассемблер строится ПОКАЖДЫЙ switch,
    а не один раз в конструкторе — адрес рецепта меняется каждой заменой)."""
    orch._full_replace_planner.kwargs["proc_dicts_fn"]({"processes": [], "wires": []})


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
    _build(orch)

    expected = sys_config.telemetry.publish.model_dump()
    assert _CaptureAssembler.last["telemetry_dict"] == expected
    assert _CaptureAssembler.last["telemetry_dict"]["metrics"]["fps"]["enabled"] is False


def test_hot_swap_no_telemetry_passes_none(monkeypatch) -> None:
    """Нет глобальной telemetry.publish → telemetry_dict=None (backward-compat)."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    orch = _StubOrchestrator(sys_config.model_dump())

    configure_topology_engine(orch)
    _build(orch)

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


def test_hot_swap_forwards_layer_addresses(monkeypatch) -> None:
    """Task 5.12 (блокер ревью 2): пересозданные switch'ем процессы обязаны получить
    адреса слоёв — иначе сохранённый спутник им не применяется, `observability.persist`
    на них отказывает, а provenance не может назвать источник."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    orch = _StubOrchestrator(
        sys_config.model_dump(),
        extra_config={
            "observability_recipe_path": "recipes/demo.yaml",
            "observability_config_path": "backend/config/system.yaml",
        },
    )

    configure_topology_engine(orch)
    _build(orch)

    assert _CaptureAssembler.last["recipe_path"] == "recipes/demo.yaml"
    assert _CaptureAssembler.last["app_config_path"] == "backend/config/system.yaml"


def test_hot_swap_resolves_recipe_path_per_build(monkeypatch) -> None:
    """Адрес рецепта резолвится на КАЖДУЮ сборку: ассемблер живёт всё время работы PM,
    а рецепт меняется каждым switch — зашитый в конструктор путь остался бы от первого."""
    _patch_engine(monkeypatch)
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    orch = _StubOrchestrator(sys_config.model_dump(), extra_config={"observability_recipe_path": "recipes/a.yaml"})

    configure_topology_engine(orch)
    _build(orch)
    assert _CaptureAssembler.last["recipe_path"] == "recipes/a.yaml"

    # Рецепт сменился (switch) — следующая сборка обязана увидеть новый адрес.
    orch._extra_config["observability_recipe_path"] = "recipes/b.yaml"
    _build(orch)
    assert _CaptureAssembler.last["recipe_path"] == "recipes/b.yaml"
