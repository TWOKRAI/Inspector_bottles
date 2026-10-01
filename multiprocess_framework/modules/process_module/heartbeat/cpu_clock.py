# -*- coding: utf-8 -*-
"""CpuClock — загрузка процесса в ядрах по счётчику тактов, а не по тикам.

Зачем не psutil: на Windows ``psutil.Process.cpu_times()`` тик-сэмплирует планировщик
(шаг ~15.6 мс) и на коротких окнах врал на порядки — нагрузку прятал/множил в сотню раз.
Нужны измеренные ядра, а не оценка по тикам.

Как считаем: ``QueryProcessCycleTime`` (kernel32) отдаёт число тактов, отработанных всеми
потоками процесса. Делим на частоту из реестра (``~MHz`` у CentralProcessor\\0) и получаем
секунды CPU. ``sample()`` — дельта CPU-секунд к дельте стенного времени = ядра.

Почему без калибровки: калибровка busy-циклом под нагрузкой стенда дала 2.76 ГГц против
3.10 ГГц по реестру (Task 4.6) — сама калибровка врёт сильнее, чем константа из реестра.
Частота берётся один раз и не подстраивается.

Fallback (не Windows или ctypes/реестр не ответили): ``time.process_time()`` —
``method == "process_time"``. Точность там задаёт ОС, но порядок величины верный.
"""

from __future__ import annotations

import functools
import sys
import time

_IS_WINDOWS = sys.platform == "win32"


class CpuClock:
    """Часы CPU процесса. ``method``: "cycles" (такты) | "process_time" (fallback)."""

    def __init__(self) -> None:
        self.method: str = "process_time"
        self._cycles_of_process = None  # callable() -> int, только при method == "cycles"
        self._hz: float = 0.0
        self._last: tuple[float, float] | None = None
        if _IS_WINDOWS:
            self._try_init_cycles()

    def _try_init_cycles(self) -> None:
        """Подключить счётчик тактов; при любой неудаче остаться на process_time."""
        try:
            import ctypes
            from ctypes import wintypes
            import winreg

            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            # Без argtypes псевдо-хэндл -1 даёт OverflowError (замерено).
            k32.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
            k32.QueryProcessCycleTime.restype = wintypes.BOOL
            handle = k32.GetCurrentProcess()

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                mhz, _ = winreg.QueryValueEx(key, "~MHz")
            hz = float(mhz) * 1e6
            if hz <= 0.0:
                return

            def _read() -> int:
                cycles = ctypes.c_ulonglong(0)
                if not k32.QueryProcessCycleTime(handle, ctypes.byref(cycles)):
                    raise OSError("QueryProcessCycleTime failed")
                return cycles.value

            _read()  # пробный вызов: упадёт здесь, а не в hot path heartbeat
            self._cycles_of_process = _read
            self._hz = hz
            self.method = "cycles"
        except Exception:  # noqa: BLE001 — любой сбой ctypes/реестра -> fallback, не падение процесса
            self._cycles_of_process = None
            self.method = "process_time"

    def seconds_total(self) -> float:
        """Суммарные CPU-секунды процесса с его старта (монотонно, float)."""
        if self._cycles_of_process is not None:
            return self._cycles_of_process() / self._hz
        return float(time.process_time())

    def sample(self) -> float | None:
        """Ядра (dCPU/dWall) с предыдущего ``sample()``; None на первом вызове."""
        cpu_s = self.seconds_total()
        now = time.perf_counter()
        prev, self._last = self._last, (cpu_s, now)
        if prev is None:
            return None
        dwall = now - prev[1]
        if dwall <= 0.0:
            return None
        return (cpu_s - prev[0]) / dwall


@functools.cache
def process_clock() -> CpuClock:
    """Единственный экземпляр часов на процесс (общая точка отсчёта для heartbeat)."""
    return CpuClock()
