# -*- coding: utf-8 -*-
"""SPI.d0 / C-47 — ``executors`` процесса из чертежа доезжает до ``proc_dict["config"]``.

Purpose:
    ``ProcessConfig`` объявляет именованные исполнители процесса (``executors``), ``as_generic_config`` переносит их
    в ``GenericProcessConfig``; форму записи проверяет ``ExecutorManager.load_config`` / ``ExecutorSpec`` в процессе,
    чертёж только переносит. Пустое или отсутствующее значение — ключа ``executors`` в конфиге нет (как прежде).
    Все тесты — через настоящий ``SystemBlueprint`` и настоящий ``ExecutorManager`` (без фейков). Ожидания — литералы.

Public API:
    Только тесты ``test_*``.
"""

from __future__ import annotations

import threading
from typing import Any

from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

from ..topology.blueprint import SystemBlueprint

_DEVICE_IO = {"kind": "keyed", "max_workers": 4, "max_pending": 64}


def _build(process: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """``dict`` топологии (как после YAML) -> (GenericProcessConfig, proc_dict) одного процесса."""
    blueprint = SystemBlueprint.model_validate({"name": "d0", "processes": [process], "wires": []})
    (cfg,) = blueprint.build_configs()
    _name, proc_dict = cfg.build()
    return cfg, proc_dict


def test_executors_reach_generic_config_and_proc_dict() -> None:
    """(а) ``executors`` у процесса чертежа -> ``cfg.executors`` и ``proc_dict["config"]["executors"]`` те же."""
    cfg, proc_dict = _build({"process_name": "devices", "executors": {"device_io": dict(_DEVICE_IO)}})

    assert cfg.executors == {"device_io": {"kind": "keyed", "max_workers": 4, "max_pending": 64}}
    assert proc_dict["config"]["executors"] == {"device_io": {"kind": "keyed", "max_workers": 4, "max_pending": 64}}


def test_no_executors_key_config_as_before() -> None:
    """(б) без ключа: ``cfg.executors == {}`` и ключа ``executors`` в ``proc_dict["config"]`` нет (как до правки)."""
    cfg, proc_dict = _build({"process_name": "devices"})
    assert cfg.executors == {}
    assert "executors" not in proc_dict["config"]

    cfg_empty, proc_dict_empty = _build({"process_name": "devices", "executors": {}})
    assert cfg_empty.executors == {}
    assert "executors" not in proc_dict_empty["config"]


def test_built_config_is_accepted_by_executor_manager() -> None:
    """(в) цепочка: чертёж -> ``proc_dict`` -> ``ExecutorManager.load_config`` -> исполнитель ``device_io``."""
    _cfg, proc_dict = _build({"process_name": "devices", "executors": {"device_io": dict(_DEVICE_IO)}})

    worker_manager = WorkerManager(manager_name="d0", process=None)
    assert worker_manager.initialize() is True
    manager = ExecutorManager("d0_executors", worker_manager=worker_manager)
    assert manager.initialize() is True
    try:
        created = manager.load_config(proc_dict["config"].get("executors"))

        assert created == ["device_io"]
        assert manager.names() == ["device_io"]
        entry = manager.describe()["executors"]["device_io"]
        assert (entry["kind"], entry["max_workers"], entry["max_pending"]) == ("keyed", 4, 64)
    finally:
        for stop in (manager.shutdown, worker_manager.shutdown):
            thread = threading.Thread(target=stop, daemon=True)
            thread.start()
            thread.join(10.0)
