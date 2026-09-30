"""Слепые acceptance-тесты 4.8a: чтение CPU чужого процесса и самопроверка часов.

Источник истины — `plans/transport-single-policy/task-4.8.md`, п. 2 публичного API и
acceptance-пункты про самопроверку, `ProcessCpu`, `parse_proc_stat`, `winreg`.

Оракул для «ядер» — литерал: busy-цикл на одном ядре = 1.0, `sleep` = 0. Тиковый
`psutil.cpu_times` на Windows (~15.6 мс) как собственный оракул НЕ используется.

Всё, что может зависнуть, ограничено: дочерние процессы сами умирают по таймеру
(busy <= 8 с, sleep <= 8 с) и добиваются в `finally`; подпроцессы — `timeout=`.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

REPO = Path(__file__).resolve().parents[3]

BUSY = "import time\nt = time.perf_counter()\nwhile time.perf_counter() - t < 8.0:\n    pass\n"
SLEEP = "import time\ntime.sleep(8.0)\n"

WINDOW_S = 2.0  # длина окна замера по стенным часам


def _cpu_probe():
    return importlib.import_module("scripts.capacity_bench.cpu_probe")


def _report():
    return importlib.import_module("scripts.capacity_bench.report")


@contextlib.contextmanager
def _child(code: str):
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _cores_of_child(code: str) -> float:
    """Ядра дочернего процесса за окно WINDOW_S, замеренные снаружи через `ProcessCpu`."""
    probe_cls = _cpu_probe().ProcessCpu
    with _child(code) as proc:
        time.sleep(1.0)  # старт интерпретатора не должен попасть в окно
        probe = probe_cls(proc.pid)
        c0, t0 = probe.read_seconds(), time.perf_counter()
        time.sleep(WINDOW_S)
        c1, t1 = probe.read_seconds(), time.perf_counter()
    return (c1 - c0) / (t1 - t0)


class _Inflated:
    """Обёртка над настоящим `ProcessCpu`, завышающая `read_seconds` на 20 %."""

    def __init__(self, pid: int):
        self._real = _cpu_probe().ProcessCpu(pid)
        self.method = self._real.method

    def read_seconds(self) -> float:
        return self._real.read_seconds() * 1.2


def _live_children() -> set[int]:
    out = set()
    for p in psutil.Process().children(recursive=True):
        with contextlib.suppress(psutil.Error):
            if p.status() != psutil.STATUS_ZOMBIE:
                out.add(p.pid)
    return out


def test_process_cpu_busy_child_is_one_core():
    assert _cores_of_child(BUSY) == pytest.approx(1.0, abs=0.05)


def test_process_cpu_sleeping_child_is_idle():
    assert _cores_of_child(SLEEP) < 0.05


def test_process_cpu_read_seconds_is_float_and_method_matches_platform():
    """Windows -> cycles, Linux -> proc_stat, иначе psutil (литералы из контракта)."""
    probe_cls = _cpu_probe().ProcessCpu
    with _child(SLEEP) as proc:
        probe = probe_cls(proc.pid)
        assert isinstance(probe.read_seconds(), float)
        method = probe.method
    if sys.platform == "win32":
        assert method == "cycles"
    elif sys.platform.startswith("linux"):
        assert method == "proc_stat"
    else:
        assert method == "psutil"


def test_parse_proc_stat_comm_with_parens():
    """Имя со скобками и пробелами: поля считаются после ПОСЛЕДНЕЙ `)`.

    Поля: 14 utime = 777, 15 stime = 333. Наивный `split()` дал бы другие числа.
    """
    line = (
        "1234 (python (x) y) S 1 1234 1234 0 -1 4194304 5000 10 3 0 "
        "777 333 0 0 20 0 3 0 100000 12345678 1000 18446744073709551615"
    )
    assert _cpu_probe().parse_proc_stat(line) == (777, 333)


def test_parse_proc_stat_plain_comm():
    line = "42 (bash) R 1 42 42 0 -1 4194304 10 0 0 0 5 9 0 0 20 0 1 0 1 1 1"
    assert _cpu_probe().parse_proc_stat(line) == (5, 9)


def test_selfcheck_real_probe_is_one_core_and_ok():
    result = _cpu_probe().clock_selfcheck()
    assert result["ok"] is True
    assert result["measured"] == pytest.approx(1.0, abs=0.05)
    assert result["method"] in {"cycles", "proc_stat", "psutil"}


def test_selfcheck_leaves_no_live_child():
    """Дочерний busy-процесс гарантированно завершён к возврату."""
    before = _live_children()
    _cpu_probe().clock_selfcheck(seconds=1.0)
    assert _live_children() - before == set()


def test_selfcheck_inflated_probe_not_ok():
    result = _cpu_probe().clock_selfcheck(seconds=1.0, probe=_Inflated)
    assert result["ok"] is False
    assert result["measured"] > 1.10  # 1.0 * 1.2 при честных часах


def test_selfcheck_tolerance_widens_acceptance():
    """Граница с обеих сторон: тот же завышенный прибор при допуске 0.5 -> ok."""
    result = _cpu_probe().clock_selfcheck(seconds=1.0, tolerance=0.5, probe=_Inflated)
    assert result["ok"] is True


def test_inflated_selfcheck_makes_report_flag_unreliable_cpu(tmp_path):
    """Самопроверка с подменённым прибором -> в отчёте литерал про ненадёжные CPU-числа."""
    selfcheck = _cpu_probe().clock_selfcheck(seconds=1.0, probe=_Inflated)
    assert selfcheck["ok"] is False
    result = {
        "passport": {"host": "PROBEHOST", "commit": "0" * 40},
        "selfcheck": selfcheck,
        "tests": None,
        "profile": "quick",
        "cases": [],
    }
    md_path, _ = _report().write_report(result, tmp_path)
    assert "CPU-числа на этой машине ненадёжны" in md_path.read_bytes().decode("utf-8")


PKG_MODULES = ["passport", "cpu_probe", "matrix", "recipe", "fields", "report", "run_case"]

_NO_WINREG = """
import sys
sys.modules["winreg"] = None  # имитация Linux: import winreg -> ImportError
import importlib
importlib.import_module("scripts.capacity_bench")
for name in {modules!r}:
    importlib.import_module("scripts.capacity_bench." + name)
import runpy
sys.argv = ["capacity_bench", "--help"]  # __main__ импортируется через argparse --help
try:
    runpy.run_module("scripts.capacity_bench", run_name="__main__")
except SystemExit as exc:
    assert exc.code in (0, None), exc.code
print("IMPORT-OK")
"""


def test_modules_import_without_winreg():
    """`ctypes`/`winreg` только внутри Windows-ветки: импорт модулей и `--help` без winreg."""
    # Якорь: пока пакета нет — падаем ModuleNotFoundError, а не неопознанным rc подпроцесса.
    importlib.import_module("scripts.capacity_bench.cpu_probe")
    env = dict(os.environ, PYTHONPATH=str(REPO))
    proc = subprocess.run(
        [sys.executable, "-c", _NO_WINREG.format(modules=PKG_MODULES)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "IMPORT-OK" in proc.stdout
