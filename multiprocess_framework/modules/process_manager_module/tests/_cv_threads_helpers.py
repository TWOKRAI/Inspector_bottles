# -*- coding: utf-8 -*-
"""Хелперы для acceptance-тестов Task 4.6 (`cv_threads` процесса из рецепта).

Не production-код. Всё, что исполняется в spawn-ребёнке, живёт ЗДЕСЬ, на верхнем
уровне модуля (Windows-spawn переимпортирует модуль по dotted-path; модульного
кода с побочными эффектами нет).

* ``ReportChild`` — процесс-двойник: в ``__init__`` и в ``run()`` снимает
  ``cv2.getNumThreads()`` (``None`` — cv2 недоступен) и ``cv_threads`` из реального
  ``introspect.status``, пишет JSON в файл из env ``T46_REPORT``. Снимок в ``__init__`` = «значение УЖЕ
  применено до создания класса процесса».
* ``child_entry`` — цель ``mp.Process``: опционально «убирает» cv2
  (``sys.modules["cv2"] = None`` → ``import cv2`` бросает ImportError) и зовёт
  настоящий ``run_process_function`` в bundle-режиме.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

REPORT_CHILD_CLASS_PATH = "multiprocess_framework.modules.process_manager_module.tests._cv_threads_helpers.ReportChild"


def _cv_threads_now() -> Any:
    try:
        import cv2
    except ImportError:
        return None
    return cv2.getNumThreads()


def _write(key: str, value: Any) -> None:
    path = os.environ["T46_REPORT"]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data[key] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class ReportChild:
    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name
        _write("init", _cv_threads_now())
        _write("init_done", True)

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        _write("run", _cv_threads_now())
        # Что отдал бы introspect.status ЭТОГО процесса (реальный BuiltinCommands на
        # фейковых сервисах из test_introspect_commands): ключа нет → "<absent>".
        from multiprocess_framework.modules.process_module.tests.test_introspect_commands import _make

        _svc, cm = _make(worker_manager=None)
        _write("status", cm.dispatch("introspect.status").get("cv_threads", "<absent>"))

    def should_stop(self) -> bool:
        return True  # run() отчитался → _run_lifecycle выходит сразу

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def child_entry(name: str, config: Dict[str, Any], block_cv2: bool, stop_event: Any, system_stop_event: Any) -> None:
    if block_cv2:
        sys.modules["cv2"] = None  # type: ignore[assignment]  # import cv2 → ImportError
    from multiprocess_framework.modules.process_manager_module.core.bundle_contract import build_bundle
    from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function

    bundle = build_bundle(queues={}, config=config)
    run_process_function(REPORT_CHILD_CLASS_PATH, name, stop_event, bundle, system_stop_event)
