"""
Unit-тесты для config_module.tools.watcher — ConfigFileWatcher.

Пропускаются если watchdog не установлен.
"""

import json
import time
import pytest

try:
    from multiprocess_framework.modules.config_module.tools.watcher import ConfigFileWatcher

    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from multiprocess_framework.modules.config_module.core.config import Config

pytestmark = pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog not installed")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_stop(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"a": 1}))

    cfg = Config(initial_data={"a": 1})
    watcher = ConfigFileWatcher(path=config_file, config=cfg)

    assert not watcher.is_running
    watcher.start()
    assert watcher.is_running
    watcher.stop()
    assert not watcher.is_running


def test_double_start_is_safe(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"a": 1}))

    cfg = Config(initial_data={"a": 1})
    watcher = ConfigFileWatcher(path=config_file, config=cfg)

    watcher.start()
    watcher.start()  # не должно бросить исключение
    assert watcher.is_running
    watcher.stop()


def test_stop_without_start():
    cfg = Config()
    watcher = ConfigFileWatcher(path="nonexistent.json", config=cfg)
    watcher.stop()  # не должно бросить исключение


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------


def test_reload_on_file_change(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reload_called = []

    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reload_called.append(True),
        debounce_seconds=0.1,
    )
    watcher.start()

    try:
        # Даём watcher время запуститься
        time.sleep(0.3)

        # Изменяем файл
        config_file.write_text(json.dumps({"value": "updated"}))

        # Ждём обработки
        deadline = time.monotonic() + 5.0
        while cfg.get("value") != "updated" and time.monotonic() < deadline:
            time.sleep(0.2)

        assert cfg.get("value") == "updated"
        assert len(reload_called) >= 1
    finally:
        watcher.stop()
