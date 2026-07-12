"""examples/minimal_app бутится headless через run_app/build_app (Ф5.11 acceptance).

Каркас должен бутиться локально: build → start → (heartbeat) → stop без висящих
процессов. Полный CI-smoke через BackendHarness — Ф5.13; здесь — лёгкая проверка
самодостаточности «рыбы» (генерик-путь app_module, base ProcessManagerProcess).
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


from multiprocess_framework.modules.app_module import build_app, load_manifest

_APP_YAML = Path("examples/minimal_app/app.yaml")


def test_minimal_app_manifest_and_discovery() -> None:
    m = load_manifest(_APP_YAML)
    assert m.name == "Minimal App"
    assert m.version == 1
    # discovery-пути резолвнуты в абсолютные от каталога манифеста
    assert any(p.endswith("minimal_app/plugins") for p in m.discovery.plugin_paths)
    assert any(p.endswith("minimal_app/services") for p in m.discovery.service_paths)


def test_minimal_app_boots_headless() -> None:
    """build → start → 2s → stop; процесс поднялся и корректно остановлен."""
    # Свой PID-файл/лог-каталог на инстанс — ловушка «два бэкенда» (общий реестр).
    prev_pid = os.environ.get("MULTIPROCESS_PID_FILE")
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    os.environ["MULTIPROCESS_PID_FILE"] = tempfile.mktemp(suffix=".minimal.pids")
    os.environ["MULTIPROCESS_LOG_DIR"] = tempfile.mkdtemp(prefix="minimal_app_log_")

    launcher = build_app(_APP_YAML)
    assert [n for n, _ in launcher._processes] == ["ticker"]
    try:
        launcher.start()
        time.sleep(2.0)  # дать worker'у стартовать
    finally:
        launcher.stop()
        # восстановить env, чтобы не протекло в соседние тесты
        for key, prev in (("MULTIPROCESS_PID_FILE", prev_pid), ("MULTIPROCESS_LOG_DIR", prev_log)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
