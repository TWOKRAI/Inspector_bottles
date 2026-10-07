# -*- coding: utf-8 -*-
"""Тесты механизма заморозки gc — в своём интерпретаторе, не в процессе общего прогона.

``gc.freeze``/``gc.unfreeze`` и ``suspend_collection_owner`` меняют глобальное состояние процесса.
Файлы из ``collect_ignore`` (``conftest.py`` пакета) общий прогон не собирает; здесь их гоняет
дочерний ``python -m pytest``, и разморозка его кучи умирает вместе с ним. Родитель не тронут.
Спек: plans/2026-10-03_lifecycle-owner-scope/task-T1-gc-isolation.md (DESIGN 2).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_MODULES = Path(__file__).resolve().parents[2]  # .../multiprocess_framework/modules
_CHILD_FLAG = "FW_GC_OWN_INTERPRETER_CHILD"
_TIMEOUT_S = 120


def _tail(text: str | bytes | None, lines: int = 30) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def test_gc_mechanism_in_own_interpreter(own_interpreter_files):
    files = own_interpreter_files
    # пустой список: pytest без путей собрал бы весь каталог, включая эту обёртку (рекурсия)
    assert files, "collect_ignore пуст: изолировать нечего"
    assert all(p.is_file() for p in files), f"нет файла среди {files}"
    if os.environ.get(_CHILD_FLAG):
        pytest.fail(f"обёртка запущена в дочернем интерпретаторе ({_CHILD_FLAG} выставлен): рекурсия")

    cmd = [sys.executable, "-m", "pytest", *map(str, files), "-q", "-rfE", "-p", "no:cacheprovider"]
    # env наследуется целиком (без PATH ребёнок падает INTERNALERROR), поверх — три ключа
    env = dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen", **{_CHILD_FLAG: "1"})
    try:
        proc = subprocess.run(
            cmd,
            cwd=_MODULES,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"дочерний pytest завис дольше {_TIMEOUT_S} с\nstdout:\n{_tail(exc.stdout)}\nstderr:\n{_tail(exc.stderr)}"
        )

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"дочерний pytest: код {proc.returncode}\n{_tail(output)}"
    summary = next((line for line in reversed(proc.stdout.splitlines()) if line.strip()), "")
    # 19 тестов владельца сборки + 7 тестов дисциплины; строка может быть «26 passed, 1 warning in …»
    assert summary.startswith("26 passed"), f"итог ребёнка: {summary!r}\n{_tail(output)}"
