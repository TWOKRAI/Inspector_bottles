"""Слепые acceptance-тесты 4.8a: паспорт машины (`passport.collect_passport`).

Источник истины — план `plans/transport-single-policy/task-4.8.md`, п. 1 публичного API.
Модуль пакета импортируется ВНУТРИ теста (`_passport`), чтобы каждый тест падал сам
`ModuleNotFoundError`, а не общей ошибкой сборки.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

EXPECTED_KEYS = {
    "host",
    "cpu_model",
    "cores_physical",
    "cores_logical",
    "freq_mhz",
    "ram_gb",
    "gpu",
    "os",
    "python",
    "cv2",
    "commit",
    "commit_dirty",
}


def _passport():
    return importlib.import_module("scripts.capacity_bench.passport")


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()


def test_passport_keys_and_commit():
    """Ключи РОВНО из контракта; `commit` = полный 40-hex SHA HEAD переданного репозитория."""
    passport = _passport().collect_passport(REPO)
    assert set(passport) == EXPECTED_KEYS
    assert re.fullmatch(r"[0-9a-f]{40}", passport["commit"])
    assert passport["commit"] == _git_head(REPO)


def test_passport_commit_dirty_is_bool_for_a_repo():
    """Для настоящего репозитория `commit_dirty` известен — bool, не None."""
    passport = _passport().collect_passport(REPO)
    assert isinstance(passport["commit_dirty"], bool)


def test_passport_cores_logical_equals_os_cpu_count():
    passport = _passport().collect_passport(REPO)
    assert passport["cores_logical"] == os.cpu_count()


def test_passport_not_a_repo_gives_none_commit_and_keeps_all_keys(tmp_path):
    """Не репозиторий: не бросает, ключи на месте, неизвестное -> None."""
    passport = _passport().collect_passport(tmp_path)
    assert set(passport) == EXPECTED_KEYS
    assert passport["commit"] is None


def test_passport_gpu_is_none_when_nvidia_smi_not_in_path(tmp_path, monkeypatch):
    """`nvidia-smi` нет в PATH -> `gpu is None`, и это не исключение."""
    monkeypatch.setenv("PATH", str(tmp_path))  # пустой каталог: ничего не найдётся
    passport = _passport().collect_passport(tmp_path)
    assert passport["gpu"] is None
