"""CPU чужого процесса снаружи и самопроверка часов.

Только stdlib и psutil: модуль (и `run_case.py`) запускают против чужого дерева, где
`scripts.*` может не быть. `ctypes`/`winreg` импортируются только внутри Windows-ветки.

Метод по платформе: Windows -> `cycles` (QueryProcessCycleTime / частота из реестра),
Linux -> `proc_stat` (utime+stime / SC_CLK_TCK), иначе `psutil` (тиковый, грубый).
Подход к тактам — как в `multiprocess_framework/.../heartbeat/cpu_clock.py`, но там
меряется СВОЙ процесс, здесь — по pid.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time

import psutil

_IS_WINDOWS = sys.platform == "win32"
_IS_LINUX = sys.platform.startswith("linux")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def parse_proc_stat(text: str) -> tuple[int, int]:
    """(utime, stime) в тиках из строки `/proc/<pid>/stat`.

    Имя процесса (поле 2) может содержать пробелы и скобки, поэтому поля считаются после
    ПОСЛЕДНЕЙ `)`: хвост начинается с поля 3, значит поля 14 и 15 — индексы 11 и 12.
    """
    tail = text[text.rindex(")") + 1 :].split()
    return int(tail[11]), int(tail[12])


def _resolve_launcher(pid: int) -> int:
    """pid интерпретатора за venv-заглушкой.

    Windows-venv: `sys.executable` — редиректор, который порождает настоящий python.exe
    отдельным процессом. Такты заглушки ~0 (замерено: busy-цикл читался как 0.0 ядра), а
    считать нужно интерпретатор — её единственного потомка. Не заглушка -> pid как есть.
    """
    if not _IS_WINDOWS or sys.executable == getattr(sys, "_base_executable", sys.executable):
        return pid
    try:
        proc = psutil.Process(pid)
        if os.path.normcase(proc.exe()) != os.path.normcase(sys.executable):
            return pid
        kids = proc.children()
        return kids[0].pid if len(kids) == 1 else pid
    except psutil.Error:
        return pid


class ProcessCpu:
    """CPU-секунды всех потоков процесса `pid` с его старта. `method`: cycles|proc_stat|psutil."""

    def __init__(self, pid: int) -> None:
        self.pid = _resolve_launcher(pid)
        self.method = "psutil"
        self._handle = None
        self._hz = 0.0
        self._k32 = None
        self._ctypes = None
        self._clk_tck = 0
        self._psutil = None
        if _IS_WINDOWS and self._init_cycles():
            self.method = "cycles"
        elif _IS_LINUX and self._init_proc_stat():
            self.method = "proc_stat"
        if self.method == "psutil":
            self._psutil = psutil.Process(pid)

    def _init_cycles(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes
            import winreg

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            # Без argtypes 64-битный хэндл усекается (замерено в cpu_clock.py).
            k32.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
            k32.QueryProcessCycleTime.restype = wintypes.BOOL
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                mhz, _ = winreg.QueryValueEx(key, "~MHz")
            hz = float(mhz) * 1e6
            handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
            if hz <= 0.0 or not handle:
                return False
            self._k32, self._ctypes, self._hz, self._handle = k32, ctypes, hz, handle
            self._cycles()  # пробный вызов: упадёт здесь, а не посреди замера
            return True
        except Exception:  # noqa: BLE001 — любой сбой ctypes/реестра -> psutil, не падение бенча
            self.close()
            return False

    def _init_proc_stat(self) -> bool:
        try:
            self._clk_tck = os.sysconf("SC_CLK_TCK")
            self._proc_stat_seconds()
            return True
        except (OSError, ValueError, IndexError):
            return False

    def _cycles(self) -> float:
        c = self._ctypes.c_ulonglong(0)
        if not self._k32.QueryProcessCycleTime(self._handle, self._ctypes.byref(c)):
            raise OSError("QueryProcessCycleTime failed")
        return c.value / self._hz

    def _proc_stat_seconds(self) -> float:
        with open(f"/proc/{self.pid}/stat", encoding="utf-8", errors="replace") as f:
            utime, stime = parse_proc_stat(f.read())
        return (utime + stime) / self._clk_tck

    def read_seconds(self) -> float:
        if self.method == "cycles":
            return float(self._cycles())
        if self.method == "proc_stat":
            return float(self._proc_stat_seconds())
        t = self._psutil.cpu_times()
        return float(t.user + t.system)

    def close(self) -> None:
        """Закрыть Windows-хэндл процесса (на других платформах — no-op)."""
        handle, self._handle = self._handle, None
        if handle and self._k32 is not None:
            self._k32.CloseHandle(handle)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001, S110 — деструктор при выходе интерпретатора
            pass


def clock_selfcheck(seconds: float = 2.0, tolerance: float = 0.05, probe=ProcessCpu) -> dict:
    """Busy-цикл на одном ядре в дочернем процессе, измеренный снаружи через `probe`.

    Честные часы дают 1.0 ядра; `ok` = `abs(measured - 1.0) <= tolerance`. Меряется ДЕЛЬТА
    двух чтений (не абсолютное значение: интерпретатор уже отработал старт). Дочерний
    процесс гарантированно убит и дожат `wait()` к возврату.
    """
    code = f"import time\nt = time.perf_counter()\nwhile time.perf_counter() - t < {seconds + 5}:\n    pass\n"
    child = subprocess.Popen([sys.executable, "-c", code])
    reader = None
    try:
        time.sleep(0.3)  # прогрев: старт интерпретатора не должен попасть в окно
        reader = probe(child.pid)
        s0, t0 = reader.read_seconds(), time.perf_counter()
        time.sleep(seconds)
        s1, t1 = reader.read_seconds(), time.perf_counter()
        measured = (s1 - s0) / (t1 - t0)
        return {"measured": measured, "ok": abs(measured - 1.0) <= tolerance, "method": reader.method}
    finally:
        # Потомки первыми: за venv-заглушкой на Windows busy-цикл крутит внук, а не child.
        with contextlib.suppress(psutil.Error):
            for grandchild in psutil.Process(child.pid).children(recursive=True):
                grandchild.kill()
        child.kill()
        child.wait()
        close = getattr(reader, "close", None)
        if close is not None:
            close()
