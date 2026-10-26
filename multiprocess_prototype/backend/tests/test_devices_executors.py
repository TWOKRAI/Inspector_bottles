# -*- coding: utf-8 -*-
"""SPI.d3 — процесс ``devices`` топологии прототипа несёт исполнитель ``device_io`` (4 рабочих, очередь 64).

Purpose:
    10 команд данных робота регистрируются с ``executor="device_io"`` (SPI.d2); без исполнителя в процессе они идут
    запасным путём. Проверка — настоящей сборкой: тот же путь, что у сборщика прототипа (``SystemBuilder`` по
    манифесту), затем ``ExecutorManager.load_config`` принимает секцию ``config["executors"]`` процесса ``devices``.
    Ожидания — литералы. Сборка не спавнит процессы (см. ``test_build_characterization.py``).
    Сторож строкового контракта: исполнители операций каталога хаба ⊆ исполнителям процесса ``devices``.

Public API:
    Только тесты ``test_*``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

# backend/tests/<file> → parents[3] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RECIPES = ["phone_sketch", "hikvision_letter_robot"]


def _devices_config(recipe: str) -> dict:
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, recipe).build()
    procs = dict(launcher._processes)
    return procs["devices"]["config"]


@pytest.mark.parametrize("recipe", RECIPES)
def test_devices_process_declares_device_io_executor(recipe: str) -> None:
    """Топология -> сборка: у ``devices`` исполнитель ``device_io`` с 4 рабочими и очередью 64."""
    config = _devices_config(recipe)

    assert config["executors"] == {"device_io": {"max_workers": 4, "max_pending": 64}}


def test_executor_manager_accepts_devices_executors() -> None:
    """``ExecutorManager.load_config`` принимает секцию процесса: исполнитель ``device_io`` создан (keyed, 4, 64)."""
    config = _devices_config("phone_sketch")

    worker_manager = WorkerManager(manager_name="d3", process=None)
    assert worker_manager.initialize() is True
    manager = ExecutorManager("d3_executors", worker_manager=worker_manager)
    assert manager.initialize() is True
    try:
        created = manager.load_config(config.get("executors"))

        assert created == ["device_io"]
        assert manager.names() == ["device_io"]
        entry = manager.describe()["executors"]["device_io"]
        assert (entry["kind"], entry["max_workers"], entry["max_pending"]) == ("keyed", 4, 64)
    finally:
        for stop in (manager.shutdown, worker_manager.shutdown):
            thread = threading.Thread(target=stop, daemon=True)
            thread.start()
            thread.join(10.0)


@pytest.mark.parametrize("recipe", RECIPES)
def test_catalog_executors_are_declared_by_devices_process(recipe: str) -> None:
    """Имя исполнителя — строковый контракт Services -> топология: каждый ``executor`` операций команд хаба
    (``kinds.DEFAULT_SOURCES``) объявлен в секции ``executors`` процесса ``devices`` (ревью ветки SPI, п.5)."""
    from Services.device_hub.kinds import DEFAULT_SOURCES

    named = {spec.executor for source in DEFAULT_SOURCES for spec in source.ops if spec.executor is not None}
    assert named == {"device_io"}
    assert named <= set(_devices_config(recipe)["executors"])
