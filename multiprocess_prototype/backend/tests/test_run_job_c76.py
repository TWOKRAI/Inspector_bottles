"""C-76: слепые приёмочные тесты Job Object лаунчера (написаны до правки ``run.py``).

Что проверяем: на Windows ``run.default_relaunch`` не оставляет живых потомков, когда лаунчер
умер (``taskkill /PID <лаунчер> /F`` без ``/T``) и когда приложение вышло само; смерть
переходника (M2) по-прежнему убивает ребёнка и теперь убивает и его потомка.

Цепочка (настоящие процессы, ``skipif(os.name != "nt")``)::

    launcher.py -> переходник -> child.py -> переходник потомка -> grandchild.py

``launcher.py`` запускается отдельным процессом; PID берутся из файлов-меток, а не из
``Popen.pid`` теста (под pytest ``sys.executable`` — переходник). Живость — через
``OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION)`` + ``GetExitCodeProcess == 259``;
handle открывается, пока процесс жив (защита от повторного использования PID).
Убийство — ``taskkill /PID <pid> /F`` без ``/T``. Все ожидания — опрос с дедлайном.
Зачистка всех записанных PID — в teardown фикстуры (по PID/handle, без глобального taskkill).

Ожидаемые значения — литералы из спеки: живых 0, rc 1, rc 3.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

_windows_only = pytest.mark.skipif(os.name != "nt", reason="C-76: Job Object лаунчера — только Windows")

# Корень worktree, из которого лаунчер импортирует run.py (tests -> backend -> multiprocess_prototype -> корень).
_ROOT = Path(__file__).resolve().parents[3]
# Переходник .venv основной копии (литерал из спеки): без него цепочка из трёх процессов не воспроизводится.
_PY = Path(r"D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.venv\Scripts\python.exe")
if not _PY.exists():  # другая машина: под pytest из .venv sys.executable и есть переходник
    _PY = Path(sys.executable)

_STARTUP_DEADLINE_S = 30.0  # подъём цепочки: три запуска python + импорт run.py
_EVENT_DEADLINE_S = 5.0  # исход события (смерть процессов, метка rc) — по спеке
_RC_AFTER_EXIT_DEADLINE_S = 15.0  # метка rc при нормальном выходе приложения (J3)
_STILL_ACTIVE = 259

# --------------------------------------------------------------------------------------
# заглушки (пишутся в tmp_path)
# --------------------------------------------------------------------------------------

_PRELUDE = """
import json, os, sys, time
def put(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
"""

# argv: корень worktree, PY, каталог меток, режим child
_LAUNCHER = (
    _PRELUDE
    + """
root, py, d, mode = sys.argv[1:5]
sys.path.insert(0, root)
import multiprocess_prototype.run as run
put(os.path.join(d, "launcher.mod"), os.path.abspath(run.__file__))
put(os.path.join(d, "launcher.pid"), str(os.getpid()))
rc = run.default_relaunch(py, [py, os.path.join(d, "child.py"), mode, d, py])
put(os.path.join(d, "launcher.rc"), str(rc))
"""
)

# argv: режим (sleep | exit3 | first), каталог меток, PY
_CHILD = (
    _PRELUDE
    + """
import subprocess
mode, d, py = sys.argv[1:4]
def spawn():
    subprocess.Popen([py, os.path.join(d, "grandchild.py"), d], stdin=subprocess.DEVNULL)
if mode == "first":
    spawn()
put(os.path.join(d, "child.json"), json.dumps({"pid": os.getpid(), "ppid": os.getppid()}))
if mode != "first":
    spawn()
end = time.time() + 10
while not os.path.exists(os.path.join(d, "gc.json")) and time.time() < end:
    time.sleep(0.02)
if mode == "exit3":
    sys.exit(3)
time.sleep(120)
"""
)

_GRANDCHILD = (
    _PRELUDE
    + """
d = sys.argv[1]
put(os.path.join(d, "gc.json"), json.dumps({"pid": os.getpid(), "ppid": os.getppid()}))
time.sleep(120)
"""
)

# --------------------------------------------------------------------------------------
# живость и убийство по PID
# --------------------------------------------------------------------------------------

if os.name == "nt":
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.GetExitCodeProcess.restype = wintypes.BOOL
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateProcess.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001  # TerminateProcess в зачистке (handle уже держит PID от повторного использования)


class _Proc:
    """Процесс цепочки: PID + handle, открытый в момент, когда процесс ещё жив."""

    def __init__(self, name: str, pid: int) -> None:
        self.name = name
        self.pid = pid
        # None: открыть не удалось -> процесс уже мёртв (PID не занят никем из держащих handle).
        self.handle: int | None = _k32.OpenProcess(
            _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_TERMINATE, False, pid
        )

    def alive(self) -> bool:
        if not self.handle:
            return False
        code = wintypes.DWORD(0)
        if not _k32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE

    def terminate(self) -> None:
        if self.alive():
            _k32.TerminateProcess(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


def _taskkill(pid: int) -> None:
    """``taskkill /PID <pid> /F`` без ``/T``; кодировку вывода не разбираем."""
    res = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=20)
    assert res.returncode == 0, f"taskkill /PID {pid} /F завершился с кодом {res.returncode}"


def _poll(cond: Callable[[], bool], deadline_s: float, step_s: float = 0.05) -> bool:
    end = time.monotonic() + deadline_s
    while True:
        if cond():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(step_s)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # нет файла или ещё не дописан — опрос повторит


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# цепочка
# --------------------------------------------------------------------------------------


class _Chain:
    """Одна поднятая цепочка: лаунчер как отдельный процесс + метки + handles."""

    NAMES = ("launcher", "redir_child", "child", "redir_gc", "gc")

    def __init__(self, workdir: Path, mode: str) -> None:
        self.dir = workdir
        self.mode = mode
        self.procs: dict[str, _Proc] = {}
        self.popen: subprocess.Popen | None = None

    # -- запуск ------------------------------------------------------------------------

    def start(self) -> None:
        if not _PY.exists():
            pytest.skip(f"нет интерпретатора основной копии: {_PY}")
        (self.dir / "launcher.py").write_text(_LAUNCHER, encoding="utf-8")
        (self.dir / "child.py").write_text(_CHILD, encoding="utf-8")
        (self.dir / "grandchild.py").write_text(_GRANDCHILD, encoding="utf-8")
        out = open(self.dir / "launcher.out", "wb")  # noqa: SIM115 - закрываем сразу после Popen
        try:
            self.popen = subprocess.Popen(
                [str(_PY), str(self.dir / "launcher.py"), str(_ROOT), str(_PY), str(self.dir), self.mode],
                cwd=self.dir,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        finally:
            out.close()

        def _ready() -> bool:
            return (
                all(_read_json(self.dir / name) is not None for name in ("child.json", "gc.json"))
                and _read_int(self.dir / "launcher.pid") is not None
            )

        if not _poll(_ready, _STARTUP_DEADLINE_S):
            pytest.fail(f"цепочка не поднялась за {_STARTUP_DEADLINE_S} с; launcher.out:\n{self._out_tail()}")

    def open_handles(self) -> None:
        """Открыть handles всех пяти PID из меток (как можно раньше после появления меток)."""
        child = _read_json(self.dir / "child.json")
        gc = _read_json(self.dir / "gc.json")
        launcher_pid = _read_int(self.dir / "launcher.pid")
        assert child is not None and gc is not None and launcher_pid is not None
        pids = {
            "launcher": launcher_pid,
            "redir_child": int(child["ppid"]),
            "child": int(child["pid"]),
            "redir_gc": int(gc["ppid"]),
            "gc": int(gc["pid"]),
        }
        for name, pid in pids.items():
            self.procs[name] = _Proc(name, pid)

    def assert_launcher_module_is_worktree(self) -> None:
        mod = (self.dir / "launcher.mod").read_text(encoding="utf-8").strip()
        assert Path(mod).resolve().is_relative_to(_ROOT), f"лаунчер импортировал run.py не из worktree: {mod}"

    def assert_all_alive(self) -> None:
        pids = {n: p.pid for n, p in self.procs.items()}
        assert len(set(pids.values())) == len(self.NAMES), f"PID цепочки не различны: {pids}"
        dead = [n for n, p in self.procs.items() if not p.alive()]
        assert dead == [], f"до убийства не живы: {dead}; PID: {pids}\nlauncher.out:\n{self._out_tail()}"

    # -- действия и ожидания -----------------------------------------------------------

    def kill(self, name: str) -> None:
        _taskkill(self.procs[name].pid)

    def alive_of(self, names: list[str]) -> list[str]:
        return [n for n in names if self.procs[n].alive()]

    def wait_dead(self, names: list[str], deadline_s: float = _EVENT_DEADLINE_S) -> list[str]:
        """Ждать смерти всех ``names``; вернуть тех, кто ещё жив по дедлайну (пусто = успех)."""
        _poll(lambda: not self.alive_of(names), deadline_s)
        return self.alive_of(names)

    def wait_rc(self, deadline_s: float) -> int | None:
        rc_path = self.dir / "launcher.rc"
        box: list[int] = []

        def _got() -> bool:
            val = _read_int(rc_path)
            if val is not None:
                box.append(val)
            return val is not None

        return box[0] if _poll(_got, deadline_s) else None

    # -- зачистка ----------------------------------------------------------------------

    def cleanup(self) -> None:
        # Метки, прочитанные только теперь (тест упал до open_handles), тоже зачищаем.
        if not self.procs and (self.dir / "launcher.pid").exists():
            try:
                self.open_handles()
            except AssertionError:
                pass
        for proc in self.procs.values():
            proc.terminate()
        if self.popen is not None:
            try:
                self.popen.kill()
                self.popen.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for proc in self.procs.values():
            proc.close()

    def _out_tail(self) -> str:
        try:
            return (self.dir / "launcher.out").read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            return "<нет launcher.out>"


@pytest.fixture
def make_chain(tmp_path: Path) -> Iterator[Callable[[str], _Chain]]:
    chains: list[_Chain] = []

    def _make(mode: str) -> _Chain:
        chain = _Chain(tmp_path, mode)
        chains.append(chain)
        return chain

    try:
        yield _make
    finally:
        for chain in chains:
            chain.cleanup()


def _up(make_chain: Callable[[str], _Chain], mode: str) -> _Chain:
    """Цепочка поднята, handles открыты, все пять PID живы (для режимов, где child не выходит)."""
    chain = make_chain(mode)
    chain.start()
    chain.open_handles()
    chain.assert_launcher_module_is_worktree()
    chain.assert_all_alive()
    return chain


# --------------------------------------------------------------------------------------
# J1, J1b, J2a, J2b, J3
# --------------------------------------------------------------------------------------

_DESCENDANTS = ["redir_child", "child", "redir_gc", "gc"]


@_windows_only
def test_j1_killing_launcher_leaves_no_live_descendants(make_chain: Callable[[str], _Chain]) -> None:
    chain = _up(make_chain, "sleep")

    chain.kill("launcher")

    survivors = chain.wait_dead(_DESCENDANTS)
    assert survivors == [], f"после убийства лаунчера живы (ожидалось 0): {survivors}"
    assert not chain.procs["launcher"].alive(), "лаунчер должен быть мёртв"


@_windows_only
def test_j1b_grandchild_spawned_first_dies_with_launcher(make_chain: Callable[[str], _Chain]) -> None:
    chain = _up(make_chain, "first")

    chain.kill("launcher")

    survivors = chain.wait_dead(["gc", "redir_gc"])
    assert survivors == [], f"потомок, порождённый первой строкой child, пережил лаунчер: {survivors}"


@_windows_only
def test_j2a_killing_adapter_kills_child_and_returns_one(make_chain: Callable[[str], _Chain]) -> None:
    chain = _up(make_chain, "sleep")
    assert chain.procs["launcher"].alive(), "лаунчер должен быть жив перед убийством переходника"

    chain.kill("redir_child")

    survivors = chain.wait_dead(["child"])
    assert survivors == [], "child жив после убийства переходника"
    rc = chain.wait_rc(_EVENT_DEADLINE_S)
    assert rc == 1, f"default_relaunch должен вернуть 1 (метка launcher.rc), получено {rc!r}"


@_windows_only
def test_j2b_killing_adapter_kills_grandchild_chain(make_chain: Callable[[str], _Chain]) -> None:
    chain = _up(make_chain, "sleep")
    assert chain.procs["launcher"].alive(), "лаунчер должен быть жив перед убийством переходника"

    chain.kill("redir_child")

    survivors = chain.wait_dead(["redir_gc", "gc"])
    assert survivors == [], f"после убийства переходника живы потомки ребёнка: {survivors}"


@_windows_only
def test_j3_normal_exit_returns_three_and_grandchild_dies(make_chain: Callable[[str], _Chain]) -> None:
    # child выходит с кодом 3 сразу после появления gc.json: к моменту открытия handles он (и,
    # после правки, потомок) может быть уже мёртв — «жив до события» здесь не утверждаем.
    chain = make_chain("exit3")
    chain.start()
    chain.open_handles()
    chain.assert_launcher_module_is_worktree()

    rc = chain.wait_rc(_RC_AFTER_EXIT_DEADLINE_S)
    assert rc == 3, f"default_relaunch должен вернуть ровно 3 (метка launcher.rc), получено {rc!r}"

    survivors = chain.wait_dead(["gc", "redir_gc"])
    assert survivors == [], f"после выхода приложения (rc 3) живы потомки: {survivors}"
