"""
Слепые приёмочные тесты: WindowsConsole.close() не отсоединяет процесс от чужой консоли.

Дефект: когда у процесса есть консоль без окна (GetConsoleWindow() == 0, например ConPTY),
AllocConsole() отказывает (возвращает 0), но close() всё равно вызывал FreeConsole() и
отсоединял процесс от его собственной консоли.

Критерий A (юнит, подмена ctypes.windll.kernel32 — граница ОС):
  * AllocConsole отказал -> close() не вызывает FreeConsole;
  * AllocConsole удался  -> close() вызывает FreeConsole ровно один раз;
  * окно уже есть        -> AllocConsole и FreeConsole не вызываются.

Критерий B (реальные объекты, только win32): create()+close() в ОТДЕЛЬНОМ дочернем python.exe;
число процессов консоли (GetConsoleProcessList) после close() равно числу до create().
Реальный create/close нельзя гонять в процессе pytest: он отсоединил бы сам pytest от консоли.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ..platforms.windows import WindowsConsole

# multiprocess_framework/modules/console_module/tests/<файл> -> корень репозитория (parents[4])
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _make_ctypes_mock(hwnd: int, alloc_result: int) -> MagicMock:
    """ctypes с kernel32/user32; GetConsoleWindow()==hwnd, AllocConsole()==alloc_result."""
    ctypes_mock = MagicMock()
    kernel32 = MagicMock()
    user32 = MagicMock()

    kernel32.GetConsoleWindow.return_value = hwnd
    kernel32.AllocConsole.return_value = alloc_result
    kernel32.FreeConsole.return_value = 1
    kernel32.SetConsoleTitleW.return_value = 1
    kernel32.GetStdHandle.return_value = MagicMock()
    kernel32.WriteConsoleW.return_value = 1
    user32.ShowWindow.return_value = 1

    ctypes_mock.windll.kernel32 = kernel32
    ctypes_mock.windll.user32 = user32
    return ctypes_mock


def _create_then_close(hwnd: int, alloc_result: int) -> MagicMock:
    """create("t") + close() под подменой ctypes; возвращает подменённый kernel32."""
    ctypes_mock = _make_ctypes_mock(hwnd=hwnd, alloc_result=alloc_result)
    with patch.dict("sys.modules", {"ctypes": ctypes_mock}):
        console = WindowsConsole()
        console.create("t")
        console.close()
    return ctypes_mock.windll.kernel32


class TestCloseDetachContractMocked:
    """Критерий A. Работает на любой платформе (kernel32 подменён)."""

    def test_close_does_not_free_console_when_alloc_refused(self):
        """Окна нет, AllocConsole отказал (0) -> процесс уже в чужой консоли -> FreeConsole 0 раз."""
        kernel32 = _create_then_close(hwnd=0, alloc_result=0)

        kernel32.AllocConsole.assert_called_once()
        assert kernel32.FreeConsole.call_count == 0

    def test_close_frees_console_exactly_once_when_alloc_succeeded(self):
        """Окна нет, AllocConsole удался (1) -> консоль наша -> FreeConsole ровно 1 раз."""
        kernel32 = _create_then_close(hwnd=0, alloc_result=1)

        kernel32.AllocConsole.assert_called_once()
        assert kernel32.FreeConsole.call_count == 1

    def test_existing_window_neither_allocates_nor_frees(self):
        """Окно уже есть (GetConsoleWindow()!=0) -> AllocConsole 0 раз и FreeConsole 0 раз."""
        kernel32 = _create_then_close(hwnd=12345, alloc_result=1)

        assert kernel32.AllocConsole.call_count == 0
        assert kernel32.FreeConsole.call_count == 0


# Скрипт дочернего процесса: печатает «RESULT <до> <после>» — число процессов консоли.
_CHILD_SCRIPT = """
import ctypes

kernel32 = ctypes.windll.kernel32


def console_process_count():
    buf = (ctypes.c_uint * 8)()
    return kernel32.GetConsoleProcessList(buf, 8)


from multiprocess_framework.modules.console_module.platforms.windows import WindowsConsole

before = console_process_count()
console = WindowsConsole()
console.create("t")
console.close()
after = console_process_count()
print("RESULT", before, after)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="GetConsoleProcessList/AllocConsole — только Windows")
def test_real_create_close_keeps_process_attached_to_its_console():
    """Критерий B: после create()+close() процесс остаётся в своей консоли (число до == число после)."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(_REPO_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,  # свою консоль без окна: тест не зависит от состояния родителя
            timeout=60,
            text=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("дочерний процесс create()/close() завис дольше 60 с")

    result_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert result_lines, f"нет строки RESULT; rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    _, before_s, after_s = result_lines[-1].split()
    before, after = int(before_s), int(after_s)

    if before == 0:
        pytest.skip("у дочернего процесса нет консоли в этой среде (GetConsoleProcessList()==0 до create)")

    assert after == before, (
        f"число процессов консоли до create={before}, после close={after} (процесс отсоединён от консоли)"
    )
