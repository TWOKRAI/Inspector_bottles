"""ProcessTreeGuard — OS-уровневая гарантия завершения всего дерева процессов.

Закрытие окна / падение launcher не должно оставлять воркеров-сирот. Полагаться
только на обход PPID (psutil) ненадёжно: после смерти родителя цепочка рвётся,
плюс гонки рестарта и переиспользования PID. Правильный путь — примитивы ОС:

* **Windows:** Job Object с ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. Оркестратор
  (и все его потомки по наследованию job) приписаны к job. ``TerminateJobObject``
  валит дерево атомарно, а закрытие последнего хэндла job (выход/краш launcher) —
  автоматически. Launcher в job НЕ входит → управляет teardown'ом сам.
* **POSIX (Linux/macOS):** оркестратор делает ``setsid()`` (новая сессия), его
  потомки наследуют process group. ``killpg(pgid)`` валит группу, не трогая
  launcher (он в своей группе).

Любой потомок — registry-процесс, ``subprocess.Popen`` плагина, SDK-процесс —
попадает в дерево автоматически, неважно как порождён. Если примитив ОС
недоступен (нет прав / экзотическая платформа), используется portable
psutil-fallback (рекурсивный обход потомков).
"""

from __future__ import annotations

import os
import sys
from typing import Optional


class ProcessTreeGuard:
    """Удерживает OS-примитив, гарантирующий гибель дерева оркестратора.

    Жизненный цикл:
        guard.install()              # ДО спавна оркестратора (Windows: создать job)
        ...spawn оркестратора...
        guard.adopt(pm_pid)          # ПОСЛЕ start() (Win: assign job; POSIX: запомнить pgid)
        ...работа...
        guard.kill_tree()            # авторитетный teardown (после graceful)
    """

    def __init__(self, logger=None) -> None:
        self._logger = logger
        self._is_windows = sys.platform == "win32"
        # Windows: HANDLE job-объекта (держим открытым → KILL_ON_JOB_CLOSE активен).
        self._job = None
        # POSIX: pid оркестратора (= pgid после его setsid()).
        self._pm_pid: Optional[int] = None

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def wants_new_session(self) -> bool:
        """POSIX: оркестратор должен сделать setsid() при старте (новая сессия)."""
        return not self._is_windows

    def install(self) -> None:
        """Подготовить OS-примитив ДО спавна оркестратора.

        Windows: создать job с kill-on-close (дети, приписанные позже, наследуют).
        POSIX: no-op (сессию создаёт сам оркестратор через setsid; см. adopt).
        """
        if self._is_windows:
            self._install_windows_job()

    def adopt(self, pm_pid: int) -> None:
        """Привязать оркестратора (и его будущих потомков) к дереву.

        Windows: AssignProcessToJobObject — потомки PM наследуют job.
        POSIX: запомнить pid PM как pgid группы (PM уже сделал setsid).
        """
        self._pm_pid = pm_pid
        if self._is_windows and self._job is not None:
            self._assign_windows(pm_pid)

    def kill_tree(self, fallback_procs: Optional[list] = None) -> None:
        """Авторитетно снести всё дерево оркестратора.

        Args:
            fallback_procs: список psutil.Process для portable-добивания, если
                примитив ОС недоступен (снимок поддерева, снятый до остановки PM).
        """
        killed = False
        if self._is_windows:
            killed = self._terminate_windows_job()
        else:
            killed = self._terminate_posix_group()
        # Fallback: примитив ОС не сработал → portable psutil-обход.
        if not killed:
            self._kill_via_psutil(fallback_procs)

    def close(self) -> None:
        """Закрыть хэндл job (Windows). KILL_ON_JOB_CLOSE добьёт остатки дерева."""
        if self._is_windows and self._job is not None:
            try:
                self._kernel32().CloseHandle(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None

    # ------------------------------------------------------------------ #
    #  Windows: Job Object                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _kernel32():
        """kernel32 с КОРРЕКТНЫМИ argtypes/restype.

        Без явных сигнатур ctypes по умолчанию трактует аргументы как c_int (32 бит)
        и усекает 64-битные HANDLE → невалидный хэндл → access violation. Поэтому
        объявляем сигнатуры всех используемых функций явно.
        """
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        return k

    def _install_windows_job(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = self._kernel32()

            JobObjectExtendedLimitInformation = 9
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                self._warn("Job Object: CreateJobObject вернул NULL → fallback на psutil")
                return

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                self._warn("Job Object: SetInformationJobObject не удался → fallback на psutil")
                kernel32.CloseHandle(job)
                return

            self._job = job
            self._info("Job Object создан (kill-on-close): дерево оркестратора будет снесено гарантированно")
        except Exception as e:  # noqa: BLE001 — примитив не критичен, есть fallback
            self._warn(f"Job Object setup error: {e} → fallback на psutil")
            self._job = None

    def _assign_windows(self, pm_pid: int) -> None:
        try:
            kernel32 = self._kernel32()
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_TERMINATE = 0x0001
            h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pm_pid))
            if not h_proc:
                self._warn(f"Job Object: OpenProcess({pm_pid}) не удался → fallback на psutil")
                return
            ok = kernel32.AssignProcessToJobObject(self._job, h_proc)
            kernel32.CloseHandle(h_proc)
            if not ok:
                self._warn("Job Object: AssignProcessToJobObject не удался → fallback на psutil")
                return
            self._info(f"Оркестратор (pid={pm_pid}) приписан к job — потомки наследуют")
        except Exception as e:  # noqa: BLE001
            self._warn(f"Job Object assign error: {e} → fallback на psutil")

    def _terminate_windows_job(self) -> bool:
        if self._job is None:
            return False
        try:
            kernel32 = self._kernel32()
            ok = kernel32.TerminateJobObject(self._job, 1)
            if ok:
                self._info("TerminateJobObject: дерево оркестратора снесено")
                return True
        except Exception as e:  # noqa: BLE001
            self._warn(f"TerminateJobObject error: {e}")
        return False

    # ------------------------------------------------------------------ #
    #  POSIX: process group (session leader = оркестратор)                 #
    # ------------------------------------------------------------------ #

    def _terminate_posix_group(self) -> bool:
        if self._pm_pid is None:
            return False
        try:
            import signal
            import time

            pgid = os.getpgid(self._pm_pid)
            # Защита: если setsid в PM не сработал, pgid совпадёт с группой launcher —
            # killpg убил бы и нас. В этом случае отдаём управление psutil-fallback.
            if pgid == os.getpgrp():
                self._warn("POSIX: оркестратор в группе launcher (setsid не сработал) → fallback на psutil")
                return False
            os.killpg(pgid, signal.SIGTERM)
            # Дать группе секунду на graceful, затем добить. SIGKILL есть только на
            # POSIX (где этот код и работает); getattr — защита от вызова на Windows.
            time.sleep(0.5)
            try:
                os.killpg(pgid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except ProcessLookupError:
                pass  # группа уже пуста
            self._info(f"killpg({pgid}): группа оркестратора снесена")
            return True
        except ProcessLookupError:
            return True  # процесса/группы уже нет — цель достигнута
        except Exception as e:  # noqa: BLE001
            self._warn(f"killpg error: {e} → fallback на psutil")
            return False

    # ------------------------------------------------------------------ #
    #  Portable fallback: psutil рекурсивно                                #
    # ------------------------------------------------------------------ #

    def _kill_via_psutil(self, fallback_procs: Optional[list]) -> None:
        try:
            import psutil

            current = psutil.Process(os.getpid())
            by_pid: dict[int, "psutil.Process"] = {}
            for proc in list(fallback_procs or []) + current.children(recursive=True):
                if proc.pid != current.pid:
                    by_pid[proc.pid] = proc
            children = list(by_pid.values())
            if not children:
                return
            self._warn(f"psutil-fallback: добиваю {len(children)} процесс(ов) дерева")
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(children, timeout=2.0)
            for child in alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:  # noqa: BLE001
            self._warn(f"psutil-fallback error: {e}")

    # ------------------------------------------------------------------ #
    #  Логирование (best-effort)                                           #
    # ------------------------------------------------------------------ #

    def _info(self, msg: str) -> None:
        if self._logger:
            try:
                self._logger.info(msg)
            except Exception:  # noqa: BLE001
                pass

    def _warn(self, msg: str) -> None:
        if self._logger:
            try:
                self._logger.warning(msg)
            except Exception:  # noqa: BLE001
                pass
