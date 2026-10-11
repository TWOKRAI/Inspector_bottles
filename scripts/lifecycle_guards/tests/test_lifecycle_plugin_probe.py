"""Тесты автора 0.5b: опасные места плагина G3/G4 и пробы abort.

Слепая приёмка — ``test_lifecycle_plugin_probe_acceptance.py`` (не править). Здесь то, что она не
покрывает: побочные эффекты импорта плагина, ключи конфигов, классификация исхода пробы
таблицей, реальная ось на ``win32``, чужие и быстро умирающие потоки в G4.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.lifecycle_guards.probe import run as probe_run
from scripts.lifecycle_guards.tests.test_lifecycle_plugin_probe_acceptance import (
    REPO_ROOT,
    _base_env,
    _run_plugin_project,
    _section,
)

PLUGIN_KEY = "-p scripts.lifecycle_guards.pytest_plugin"


# ---------------------------------------------------------------------------
# Импорт плагина и подключение
# ---------------------------------------------------------------------------


def test_plugin_import_pulls_no_heavy_modules() -> None:
    """Плагин ``-p`` грузится до ``pytest_configure`` conftest (``spawn``): тяжёлого на импорте нет."""
    code = (
        "import sys\n"
        "import scripts.lifecycle_guards.pytest_plugin\n"
        "heavy = ('multiprocessing', 'PySide6', 'multiprocess_framework')\n"
        "print('LOADED', sorted(m for m in heavy if m in sys.modules))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_base_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "LOADED []" in proc.stdout, proc.stdout + proc.stderr


def test_configs_carry_plugin_keys() -> None:
    ini = (REPO_ROOT / "multiprocess_framework/modules/pytest.ini").read_text(encoding="utf-8").splitlines()
    assert f"addopts = {PLUGIN_KEY}" in [ln.strip() for ln in ini]
    assert "pythonpath = ../.." in [ln.strip() for ln in ini]
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    opts = pyproject["tool"]["pytest"]["ini_options"]
    assert PLUGIN_KEY in opts["addopts"]
    assert opts["pythonpath"] == ["."]


def test_baseline_json_is_valid_and_keeps_measurements() -> None:
    data = json.loads((REPO_ROOT / "scripts/lifecycle_guards/probe/baseline.json").read_text(encoding="utf-8"))
    assert set(data) == {
        "suite_t1_on",
        "suite_no_conftest_offscreen",
        "suite_no_conftest_native",
        "axis",
        "history",
        "reading",
    }
    assert data["suite_t1_on"]["survived"] == 3
    assert data["suite_no_conftest_offscreen"]["wrappers"] == 1750
    assert data["axis"]["thread"] == {"crashed": 3, "of": 3}


# ---------------------------------------------------------------------------
# Классификация исхода (чистая функция, значения литералами)
# ---------------------------------------------------------------------------

_TRIGGER = "[offmain_gc] at first logger test: gc-tracked QWidget/QWindow wrappers alive-or-garbage = 5\n"


@pytest.mark.parametrize(
    ("returncode", "output", "log_text", "want"),
    [
        (0, "", _TRIGGER, "survived"),
        (0, "", "", "not-triggered"),
        (1, "", "", "not-triggered"),  # без срабатывания красный набор не «failed»: проба не отработала
        (1, "", _TRIGGER, "failed"),
        (3, "", _TRIGGER, "failed"),  # INTERNAL_ERROR pytest — не падение интерпретатора
        (None, "[timeout 900s]", _TRIGGER, "failed"),
        (3221225477, "", _TRIGGER, "crashed"),
        (3221225725, "", _TRIGGER, "crashed"),
        (3221226505, "", _TRIGGER, "crashed"),
        (-11, "", _TRIGGER, "crashed"),
        (-6, "", _TRIGGER, "crashed"),
        (139, "", _TRIGGER, "crashed"),
        (134, "", _TRIGGER, "crashed"),
        (1, "Windows fatal exception: access violation", _TRIGGER, "crashed"),
        (1, "Fatal Python error: Aborted", "", "crashed"),  # падение важнее «не сработало»
        (0, "fatal python error", _TRIGGER, "crashed"),
    ],
)
def test_classify_run_table(returncode: int | None, output: str, log_text: str, want: str) -> None:
    assert probe_run.classify_run(returncode, output, log_text, "offmain_gc") == want


def test_classify_run_trigger_line_is_mode_specific() -> None:
    # строка чужого режима не «срабатывание» этого
    assert probe_run.classify_run(0, "", "[main_gc] at first logger test: x = 1\n", "offmain_gc") == "not-triggered"


# ---------------------------------------------------------------------------
# Реальная ось
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="ось проверена только на win32")
def test_real_axis_is_alive_on_win32() -> None:
    alive, line = probe_run.check_axis(1)
    assert (alive, line) == (True, "axis: alive")


@pytest.mark.skipif(sys.platform == "win32", reason="ветка не-win32")
def test_axis_is_unchecked_off_win32() -> None:
    assert probe_run.check_axis(1) == (None, "axis: unchecked (not win32)")


# ---------------------------------------------------------------------------
# G4: чужие и быстро умирающие потоки
# ---------------------------------------------------------------------------

G4_FOREIGN_AND_FAST = """
    import _thread
    import threading
    import time

    STOP = threading.Event()

    def _foreign():
        threading.current_thread()  # создаёт _DummyThread «Dummy-N»
        STOP.wait()

    def test_foreign_thread():
        _thread.start_new_thread(_foreign, ())
        time.sleep(0.05)

    def test_dies_within_budget():
        threading.Thread(target=time.sleep, args=(0.05,), name="quick-1").start()
"""


def test_g4_ignores_dummy_threads_and_threads_that_die_within_the_wait(tmp_path: Path) -> None:
    rc, out = _run_plugin_project(tmp_path, {"test_g4_hazard.py": G4_FOREIGN_AND_FAST}, g3="off", g4="fail")
    section = _section(out)
    assert "G4 threads without scope path: 0" in section, out
    assert "Dummy-" not in section, out
    assert "quick-1" not in section, out
    assert rc == 0, out


# ---------------------------------------------------------------------------
# Дыры, найденные инъекциями ведущего (0.5b.injections.json: inj-6, inj-13)
# ---------------------------------------------------------------------------

G3_DROPPED_IN_CYCLE = """
    from multiprocess_framework.modules.base_manager import open_scope

    def test_drop_cyclic_root():
        holder = {}
        holder["self"] = holder
        holder["root"] = open_scope("cyc", budget_s=1.0)
        del holder
"""


def test_g3_final_collect_turns_a_dropped_root_into_abandoned(tmp_path: Path) -> None:
    """Итоговый ``gc.collect()`` плагина: брошенный в цикле корень виден как ``abandoned``, не ``open``."""
    rc, out = _run_plugin_project(tmp_path, {"test_g3_cycle.py": G3_DROPPED_IN_CYCLE}, g3="report", g4="off")
    section = _section(out)
    assert "G3 unclosed roots: 1" in section, out
    assert "cyc (abandoned)" in section, out
    assert rc == 0, out


_FAKE_AXIS = """
import os, signal, sys
mode = sys.argv[1]
if mode == "thread" and {crash}:
    if sys.platform == "win32":
        os._exit(-1073741819)
    os.kill(os.getpid(), signal.SIGSEGV)
print("SURVIVED main" if mode == "main" else "thread survived")
"""


def _probe_run(tmp_path: Path, crash_thread: bool) -> tuple[int, str]:
    fake = tmp_path / "fake_axis.py"
    fake.write_text(_FAKE_AXIS.format(crash=crash_thread), encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.lifecycle_guards.probe",
            "run",
            "--runs",
            "1",
            "--axis-script",
            str(fake),
            "--cwd",
            str(tmp_path),
            "--targets",
            "test_ok.py",
        ],  # fmt: skip
        cwd=REPO_ROOT,
        env=_base_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_run_refuses_the_suite_when_the_axis_is_dead(tmp_path: Path) -> None:
    rc, out = _probe_run(tmp_path, crash_thread=False)
    assert rc == 2, out
    assert "ось не живая" in out, out
    assert "run 1/1" not in out, out  # набор не запускался


def test_run_proceeds_to_the_suite_when_the_axis_is_alive(tmp_path: Path) -> None:
    rc, out = _probe_run(tmp_path, crash_thread=True)
    assert "axis: alive" in out, out
    assert "run 1/1" in out, out  # набор запущен (исход — not-triggered: приманки logger_module нет)
    assert rc == 1, out
