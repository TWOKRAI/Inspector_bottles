# -*- coding: utf-8 -*-
"""T1, хазард авторa: граница теста ловит включённую автосборку, даже если её уже вылечил тик.

Опасность: pytest-qt зовёт ``app.processEvents()`` после тела теста и перед teardown. Если в
этот момент срабатывает таймер политики памяти, ``tick()`` → ``enforce()`` выключает
автосборку раньше ``_gui_memory_boundary``. Граница вида ``violated = policy.enforce()`` тогда
видит ``False`` и пропускает нарушителя. Граница по росту счётчика ``enabled_violations`` за
тест — ловит.

Проверка — вложенный pytest в подпроцессе (внешняя сессия не отравляется включённой
автосборкой). Внутренний прогон грузит настоящий ``multiprocess_framework/modules/conftest.py``
плагином (``-p``); файлы — только во временном каталоге pytest. Внутри два теста:

* ``test_leaves_gc_enabled`` — включает автосборку и ждёт тика (> интервала 1 с); сам
  проверяет, что тик успел вылечить (иначе хазард вакуумен) → граница обязана дать ERROR;
* ``test_control_no_enable`` — то же без ``gc.enable()`` → проходит.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FAIL_TEXT = "Тест оставил автосборку gc включённой"

_INNER_TESTS = textwrap.dedent(
    """
    import gc

    from multiprocess_framework.modules.frontend_module.core.qt_gc_policy import gui_memory_policy


    def _wait_for_tick(qtbot):
        policy = gui_memory_policy()
        policy.collect_now()  # подключить таймер (сессия ставит политику до QApplication)
        assert policy.stats()["timer_attached"] is True
        return policy


    def test_leaves_gc_enabled(qtbot):
        _wait_for_tick(qtbot)
        gc.enable()
        qtbot.wait(2500)  # интервал политики 1 с: тик успевает вылечить
        assert gc.isenabled() is False, "тик не вылечил — хазард не воспроизведён"


    def test_control_no_enable(qtbot):
        _wait_for_tick(qtbot)
        qtbot.wait(2500)
        assert gc.isenabled() is False
    """
)


def test_boundary_catches_violation_healed_by_timer_tick(tmp_path):
    (tmp_path / "test_inner.py").write_text(_INNER_TESTS, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\nqt_api = pyside6\n", encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rA",
            "--tb=line",
            "-p",
            "no:cacheprovider",
            "-p",
            "multiprocess_framework.modules.conftest",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            "test_inner.py",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"rc={proc.returncode}\n{out}"
    assert _FAIL_TEXT in out, out
    # Нарушитель: тело прошло (тик вылечил), граница дала ERROR на teardown.
    assert "PASSED test_inner.py::test_leaves_gc_enabled" in out, out
    assert "ERROR test_inner.py::test_leaves_gc_enabled" in out, out
    # Контроль: без gc.enable() — ни ошибки, ни падения.
    assert "PASSED test_inner.py::test_control_no_enable" in out, out
    assert "ERROR test_inner.py::test_control_no_enable" not in out, out
    assert "FAILED" not in out, out


# ── Ред. 4 (ревью р1 №1): политика умирает тихо ─────────────────────────────────────────────────
# Опасность: тест освобождает владельца сборки мимо ``uninstall`` (``collection_owner().release()``).
# Слот пуст, автосборка — снова как до политики, а сессионная политика «установлена»: граница по
# ``enabled_violations`` дальше ничего не видит (``enforce`` мёртвого владельца — пустой), и
# следующий тест включает автосборку безнаказанно. Граница обязана заметить пустой слот.

_DEAD_TEXT = "Политику памяти сняли посреди сессии"

_INNER_DEAD = textwrap.dedent(
    """
    import gc

    from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import collection_owner


    def test_a_releases_owner():
        collection_owner().release()


    def test_b_enables_gc():
        gc.enable()
    """
)


def test_boundary_fails_when_policy_released(tmp_path):
    (tmp_path / "test_inner.py").write_text(_INNER_DEAD, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\nqt_api = pyside6\n", encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rA",
            "--tb=line",
            "-p",
            "no:cacheprovider",
            "-p",
            "multiprocess_framework.modules.conftest",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            "test_inner.py",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"rc={proc.returncode}\n{out}"
    assert _DEAD_TEXT in out, out
    # Нарушитель: тело прошло, граница дала ERROR; следующий тест — тоже (политика мертва).
    assert "PASSED test_inner.py::test_a_releases_owner" in out, out
    assert "ERROR test_inner.py::test_a_releases_owner" in out, out
    assert "ERROR test_inner.py::test_b_enables_gc" in out, out
