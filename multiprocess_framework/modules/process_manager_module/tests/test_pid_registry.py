"""Тесты PID-реестра — надёжная чистка осиротевших процессов при старте.

Проверяют:
- register_self дописывает (pid, create_time) в файл
- reap_and_reset убивает живые записанные процессы и очищает файл
- сверка create_time защищает от убийства переиспользованного PID
- clear очищает файл
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from multiprocess_framework.modules.process_manager_module.launcher import pid_registry


@pytest.fixture
def reg_path(tmp_path):
    return tmp_path / "pids.jsonl"


def test_register_self_appends_entry(reg_path):
    pid_registry.register_self(reg_path)
    entries = pid_registry._read_entries(reg_path)
    assert len(entries) == 1
    assert entries[0][0] == os.getpid()
    assert entries[0][1] is not None  # create_time записан


def test_clear_empties_file(reg_path):
    pid_registry.register_self(reg_path)
    pid_registry.clear(reg_path)
    assert pid_registry._read_entries(reg_path) == []


def test_reap_kills_recorded_live_process(reg_path):
    """reap_and_reset убивает живой процесс из реестра и очищает файл."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ct = psutil.Process(proc.pid).create_time()
        with open(reg_path, "w", encoding="utf-8") as f:
            import json

            f.write(json.dumps({"pid": proc.pid, "ct": ct}) + "\n")

        killed = pid_registry.reap_and_reset(reg_path)
        assert killed == 1
        # Процесс мёртв
        proc.wait(timeout=5)
        assert proc.poll() is not None
        # Файл очищен
        assert pid_registry._read_entries(reg_path) == []
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_reap_skips_mismatched_create_time(reg_path):
    """Если create_time не совпадает (PID переиспользован) — НЕ убиваем."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Записываем заведомо другой create_time (имитация переиспользованного PID)
        with open(reg_path, "w", encoding="utf-8") as f:
            import json

            f.write(json.dumps({"pid": proc.pid, "ct": 1.0}) + "\n")

        killed = pid_registry.reap_and_reset(reg_path)
        assert killed == 0  # не убит — create_time не совпал
        time.sleep(0.2)
        assert proc.poll() is None  # процесс жив
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_reap_skips_self(reg_path):
    """reap не убивает текущий процесс, даже если он в реестре."""
    pid_registry.register_self(reg_path)
    killed = pid_registry.reap_and_reset(reg_path)
    assert killed == 0


def test_reap_empty_file_noop(reg_path):
    assert pid_registry.reap_and_reset(reg_path) == 0
