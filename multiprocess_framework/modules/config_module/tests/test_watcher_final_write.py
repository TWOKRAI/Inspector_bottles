"""
Воспроизведение: доходит ли ConfigFileWatcher до ПОСЛЕДНЕГО содержимого файла.

Purpose:
    Для каждого способа записи конфига (на месте, tmp + os.replace, медленная и
    chunked запись) проверить, что после завершения писателя объект Config
    держит ИТОГОВОЕ содержимое файла не позже чем через 2.0 с.
Public API:
    Проверяется ConfigFileWatcher(path, config, on_reload=None,
    debounce_seconds=1.0, log_error=None); start(); stop(); is_running.
    Утверждение — только об итоге ``cfg.get("v")``, не о числе перезагрузок.
Stability: lite

Каждый тест делает N=10 независимых запусков (свой подкаталог, свой файл, свой
Config, свой watcher); тест падает, если хоть один запуск не дошёл до ``final``
(сообщение ``lost k/10``). Тело идёт в daemon-потоке с ``join(120)``.
"""

import os
import threading
import time
from pathlib import Path

import pytest

try:
    from multiprocess_framework.modules.config_module.tools.watcher import ConfigFileWatcher

    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.data_schema_module.serialization.converter import DataConverter

__all__ = [
    "test_final_content_applied_after_write_text_in_place_json",
    "test_final_content_applied_after_save_to_file_in_place_json",
    "test_final_content_applied_after_tmp_and_os_replace_yaml",
    "test_final_content_applied_after_slow_in_place_write_yaml",
    "test_final_content_applied_after_chunked_in_place_write_yaml",
    "test_final_content_applied_after_slow_in_place_write_json",
]

pytestmark = pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog not installed")

RUNS = 10  # число независимых запусков в одном тесте
WAIT_SECONDS = 2.0  # окно дебаунса 1.0 с + запас 1.0 с
START_PAUSE = 0.4  # пауза после start(), пока observer поднимется
JOIN_SECONDS = 120


def _count_lost(base: Path, filename: str, old_text: str, writer) -> int:
    """Вернуть, в скольких из RUNS запусков итог ``final`` не дошёл до Config."""
    lost = 0
    for i in range(RUNS):
        run_dir = base / f"run{i}"
        run_dir.mkdir()
        path = run_dir / filename
        path.write_text(old_text, encoding="utf-8")  # файл создан ДО start()
        cfg = Config(initial_data={"v": "old"})
        watcher = ConfigFileWatcher(path, cfg, debounce_seconds=1.0)
        watcher.start()
        try:
            time.sleep(START_PAUSE)
            writer(path)
            deadline = time.monotonic() + WAIT_SECONDS
            while cfg.get("v") != "final" and time.monotonic() < deadline:
                time.sleep(0.05)
            if cfg.get("v") != "final":
                lost += 1
        finally:
            watcher.stop()
    return lost


def _check(tmp_path, filename: str, old_text: str, writer) -> None:
    """Прогнать цикл в daemon-потоке с дедлайном и проверить ``lost 0/10``."""
    box: dict = {}

    def body():
        try:
            box["lost"] = _count_lost(tmp_path, filename, old_text, writer)
        except BaseException as exc:  # noqa: BLE001 — отдаём в основной поток
            box["error"] = exc

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(JOIN_SECONDS)
    assert not thread.is_alive(), f"завис: тело не завершилось за {JOIN_SECONDS} с"
    if "error" in box:
        raise box["error"]
    assert box["lost"] == 0, f"lost {box['lost']}/{RUNS}"


# ---------------------------------------------------------------------------
# Писатели
# ---------------------------------------------------------------------------


def _w1_write_text_json(path: Path) -> None:
    path.write_text('{"v": "final"}', encoding="utf-8")


def _w2_save_to_file_json(path: Path) -> None:
    DataConverter.save_to_file({"v": "final"}, path)


def _w3_tmp_and_replace_yaml(path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp_test")
    tmp.write_text("v: final\n", encoding="utf-8")
    os.replace(tmp, path)


def _w4_slow_in_place_yaml(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.flush()
        time.sleep(0.05)
        f.write("v: final\n")


def _w5_chunked_in_place_yaml(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("a: 1\n")
        f.flush()
        time.sleep(0.05)
        f.write("v: final\n")


def _w6_slow_in_place_json(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.flush()
        time.sleep(0.05)
        f.write('{"v": "final"}')


# ---------------------------------------------------------------------------
# Тесты (по одному на писателя)
# ---------------------------------------------------------------------------


def test_final_content_applied_after_write_text_in_place_json(tmp_path):
    _check(tmp_path, "config.json", '{"v": "old"}', _w1_write_text_json)


def test_final_content_applied_after_save_to_file_in_place_json(tmp_path):
    _check(tmp_path, "config.json", '{"v": "old"}', _w2_save_to_file_json)


def test_final_content_applied_after_tmp_and_os_replace_yaml(tmp_path):
    _check(tmp_path, "config.yaml", "v: old\n", _w3_tmp_and_replace_yaml)


def test_final_content_applied_after_slow_in_place_write_yaml(tmp_path):
    _check(tmp_path, "config.yaml", "v: old\n", _w4_slow_in_place_yaml)


def test_final_content_applied_after_chunked_in_place_write_yaml(tmp_path):
    _check(tmp_path, "config.yaml", "v: old\n", _w5_chunked_in_place_yaml)


def test_final_content_applied_after_slow_in_place_write_json(tmp_path):
    _check(tmp_path, "config.json", '{"v": "old"}', _w6_slow_in_place_json)
