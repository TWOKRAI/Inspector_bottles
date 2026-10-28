"""C-76: сторожа разработчика к ``run._start_in_kill_job`` / ``run.default_relaunch`` (HR1–HR3, HR5–HR7).

Приёмочные тесты тестера (``test_run_job_c76.py``) проверяют исход «лаунчер убит -> потомков нет».
Здесь — то, что они не ловят: политика отказов API Windows, порядок «приостановлен до старта»,
прерывание между ``Popen`` и ``NtResumeProcess`` и закрытие handle job в ``finally`` в том же процессе.

Шов отказов — тонкие функции модуля ``run`` над API (``_job_create``, ``_proc_open``, ``_job_assign``,
``_proc_resume``): тест подменяет одну из них на функцию, бросающую ``OSError`` (или
``KeyboardInterrupt``); остальные остаются настоящими, процессы — настоящие.
``subprocess.Popen`` подменяется только записывающей обёрткой над настоящим ``Popen``.

HR4 (handle job не наследуется) отдельного теста не имеет: его покрывает J1 тестера.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import multiprocess_prototype.run as run

_windows_only = pytest.mark.skipif(os.name != "nt", reason="C-76: Job Object лаунчера — только Windows")

_ROOT = Path(__file__).resolve().parents[3]
# Переходник .venv основной копии: без него цепочка переходник -> приложение -> переходник потомка не воспроизводится.
_PY = Path(r"D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.venv\Scripts\python.exe")

_STARTUP_DEADLINE_S = 30.0
_EVENT_DEADLINE_S = 5.0
_STILL_ACTIVE = 259
_REAL_POPEN = subprocess.Popen

# --------------------------------------------------------------------------------------
# живость и убийство по PID (копия приёмы тестера: без глобального taskkill)
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

_ACCESS = 0x00100000 | 0x1000 | 0x0001  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE


class _Proc:
    """PID + handle, открытый, пока процесс жив (защита от повторного использования PID)."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.handle: int | None = _k32.OpenProcess(_ACCESS, False, pid)

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


@pytest.fixture
def reaper() -> Iterator[Callable[[int], _Proc]]:
    """Открывает ``_Proc`` по PID; в teardown убивает всё открытое (упавший тест не оставит сирот)."""
    procs: list[_Proc] = []

    def _open(pid: int) -> _Proc:
        proc = _Proc(pid)
        procs.append(proc)
        return proc

    try:
        yield _open
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            proc.close()


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
        return None


def _call_with_deadline(fn: Callable, *args: object, deadline: float = 30.0) -> object:
    """Вызвать ``fn`` в daemon-потоке; зависание — красный тест. Исключение потока пробрасывается."""
    box: dict[str, object] = {}

    def _run() -> None:
        try:
            box["rc"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 — исключение потока отдаём тесту
            box["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(deadline)
    assert not thread.is_alive(), f"{fn.__name__} не вернулся за {deadline} с"
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["rc"]


def _write(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text), encoding="utf-8")


class _RecordingPopen:
    """Подмена ``subprocess.Popen``: настоящий ``Popen`` + запись объектов (для проверки ``poll()``)."""

    def __init__(self) -> None:
        self.procs: list[subprocess.Popen] = []

    def __call__(self, *args: object, **kwargs: object) -> subprocess.Popen:
        proc = _REAL_POPEN(*args, **kwargs)
        self.procs.append(proc)
        return proc


def _fail(exc: BaseException) -> Callable[..., None]:
    def _raiser(*_args: object, **_kwargs: object) -> None:
        raise exc

    return _raiser


_SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


# --------------------------------------------------------------------------------------
# HR1–HR3: политика отказов (spec п.4)
# --------------------------------------------------------------------------------------


@_windows_only
def test_hr1_job_create_failure_runs_app_unprotected_with_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сбой создания job: приложение запущено, код дошёл, в stderr предупреждение со словами «job object»."""
    monkeypatch.setattr(run, "_job_create", _fail(OSError("боевой отказ CreateJobObject")))

    rc = _call_with_deadline(run.default_relaunch, sys.executable, [sys.executable, "-c", "import sys; sys.exit(7)"])

    assert rc == 7
    assert "job object" in capsys.readouterr().err


@_windows_only
@pytest.mark.parametrize("failing", ["_proc_resume", "_proc_open"])
def test_hr2_resume_or_open_failure_kills_child_and_raises_oserror(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """Сбой ``NtResumeProcess`` / ``OpenProcess``: приостановленный ребёнок убит, ``OSError`` проброшен."""
    recorder = _RecordingPopen()
    monkeypatch.setattr(run.subprocess, "Popen", recorder)
    monkeypatch.setattr(run, failing, _fail(OSError(f"отказ {failing}")))

    with pytest.raises(OSError, match=failing):
        _call_with_deadline(run.default_relaunch, sys.executable, _SLEEPER)

    assert len(recorder.procs) == 1
    assert recorder.procs[0].poll() is not None, "ребёнок остался приостановленным (poll() is None)"


@_windows_only
def test_hr2b_nt_resume_process_nonzero_status_is_error() -> None:
    """Полярность NTSTATUS: успех = 0, любой ненулевой статус (здесь — неверный handle) -> ``OSError``."""
    with pytest.raises(OSError, match="NtResumeProcess"):
        run._proc_resume(0xDEAD)


@_windows_only
def test_hr3_assign_failure_resumes_child_and_warns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Сбой назначения в job: ребёнок возобновлён и работает (метка, код 4), предупреждение в stderr."""
    marker = tmp_path / "ran.marker"
    script = tmp_path / "child.py"
    _write(
        script,
        f"""
        import sys
        open({str(marker)!r}, "w").write("ran")
        sys.exit(4)
        """,
    )
    monkeypatch.setattr(run, "_job_assign", _fail(OSError("отказ AssignProcessToJobObject")))

    rc = _call_with_deadline(run.default_relaunch, sys.executable, [sys.executable, str(script)])

    assert rc == 4
    assert marker.read_text() == "ran", "ребёнок не возобновлён: метка не записана"
    assert "job object" in capsys.readouterr().err


# --------------------------------------------------------------------------------------
# HR6: прерывание между Popen и NtResumeProcess
# --------------------------------------------------------------------------------------


@_windows_only
def test_hr6_keyboard_interrupt_before_resume_kills_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """``KeyboardInterrupt`` между ``Popen`` и ``NtResumeProcess``: приостановленный ребёнок убит."""
    recorder = _RecordingPopen()
    monkeypatch.setattr(run.subprocess, "Popen", recorder)
    # Исключение бросает подмена прямо в вызывающем потоке: настоящий сигнал сорвал бы сессию pytest.
    monkeypatch.setattr(run, "_proc_resume", _fail(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        run._start_in_kill_job(sys.executable, _SLEEPER)

    assert len(recorder.procs) == 1
    assert recorder.procs[0].poll() is not None, "ребёнок остался приостановленным (poll() is None)"


# --------------------------------------------------------------------------------------
# цепочки с настоящими процессами: HR5, HR7
# --------------------------------------------------------------------------------------

_PRELUDE = """
import json, os, sys, time
def put(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
"""

# Потомок: пишет gc.json {pid, ppid} и спит.
_GRANDCHILD = (
    _PRELUDE
    + """
d = sys.argv[1]
put(os.path.join(d, "gc.json"), json.dumps({"pid": os.getpid(), "ppid": os.getppid()}))
time.sleep(120)
"""
)

# Ребёнок: потомок порождается ПЕРВОЙ строкой; затем child.json; затем режим.
#   hold  - спит 120 с (HR5);
#   exit3 - ждёт gc.json и файл go, выходит с кодом 3 (HR7: тест держит ребёнка живым, пока не откроет handles).
_CHILD = (
    _PRELUDE
    + """
import subprocess
d, py, mode = sys.argv[1:4]
subprocess.Popen([py, os.path.join(d, "grandchild.py"), d], stdin=subprocess.DEVNULL)
put(os.path.join(d, "child.json"), json.dumps({"pid": os.getpid(), "ppid": os.getppid()}))
if mode == "exit3":
    end = time.time() + 30
    while not (os.path.exists(os.path.join(d, "gc.json")) and os.path.exists(os.path.join(d, "go"))) \\
            and time.time() < end:
        time.sleep(0.02)
    sys.exit(3)
time.sleep(120)
"""
)

# HR5: лаунчер с обёрткой Popen: настоящий Popen, пауза 0.3 с, потом возврат объекта.
_SLOW_LAUNCHER = (
    _PRELUDE
    + """
root, py, d = sys.argv[1:4]
sys.path.insert(0, root)
import multiprocess_prototype.run as run
_orig = run.subprocess.Popen
def _slow(*a, **k):
    proc = _orig(*a, **k)
    time.sleep(0.3)
    return proc
run.subprocess.Popen = _slow
put(os.path.join(d, "launcher.pid"), str(os.getpid()))
rc = run.default_relaunch(py, [py, os.path.join(d, "child.py"), d, py, "hold"])
put(os.path.join(d, "launcher.rc"), str(rc))
"""
)


def _write_chain_scripts(d: Path) -> None:
    (d / "grandchild.py").write_text(_GRANDCHILD, encoding="utf-8")
    (d / "child.py").write_text(_CHILD, encoding="utf-8")


def _chain_pids(d: Path) -> dict[str, int]:
    child = _read_json(d / "child.json")
    gc = _read_json(d / "gc.json")
    assert child is not None and gc is not None
    return {
        "redir_child": int(child["ppid"]),
        "child": int(child["pid"]),
        "redir_gc": int(gc["ppid"]),
        "gc": int(gc["pid"]),
    }


@_windows_only
def test_hr5_child_is_suspended_until_in_job(tmp_path: Path, reaper: Callable[[int], _Proc]) -> None:
    """Порядок «до старта»: пауза между ``Popen`` и возвратом шва не даёт ребёнку выйти из job.

    С ``CREATE_SUSPENDED`` ребёнок за паузу 0.3 с не стартует, потомок рождается уже внутри job и
    умирает с лаунчером. Без него потомок успевает выйти (раньше назначения) и переживает убийство.
    """
    if not _PY.exists():
        pytest.skip(f"нет интерпретатора основной копии: {_PY}")
    _write_chain_scripts(tmp_path)
    (tmp_path / "launcher.py").write_text(_SLOW_LAUNCHER, encoding="utf-8")
    out = open(tmp_path / "launcher.out", "wb")  # noqa: SIM115 — закрываем сразу после Popen
    try:
        popen = _REAL_POPEN(
            [str(_PY), str(tmp_path / "launcher.py"), str(_ROOT), str(_PY), str(tmp_path)],
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    finally:
        out.close()
    try:
        assert _poll(
            lambda: (tmp_path / "gc.json").exists() and (tmp_path / "child.json").exists(), _STARTUP_DEADLINE_S
        ), (tmp_path / "launcher.out").read_text(encoding="utf-8", errors="replace")[-2000:]
        launcher_pid = int((tmp_path / "launcher.pid").read_text())
        launcher = reaper(launcher_pid)
        chain = {name: reaper(pid) for name, pid in _chain_pids(tmp_path).items()}
        assert launcher.alive() and all(p.alive() for p in chain.values()), "цепочка не поднята"

        res = subprocess.run(["taskkill", "/PID", str(launcher_pid), "/F"], capture_output=True, timeout=20)
        assert res.returncode == 0

        assert _poll(lambda: not any(p.alive() for p in chain.values()), _EVENT_DEADLINE_S)
        survivors = [name for name, p in chain.items() if p.alive()]
        assert survivors == [], f"после убийства лаунчера живы: {survivors}"
    finally:
        popen.kill()
        popen.wait(timeout=10)


@_windows_only
def test_hr7_job_handle_closed_in_finally_in_same_process(tmp_path: Path, reaper: Callable[[int], _Proc]) -> None:
    """Остаток job убит при нормальном выходе в том же процессе (лаунчер = pytest, остаётся жив).

    Единственный тест, различающий «закрыть handle job в ``finally``» и «положиться на выход процесса
    лаунчера»: здесь процесс не выходит. Ребёнок держится живым файлом ``go``, пока тест не открыл
    handles потомка, иначе «мёртв» нельзя отличить от «убит закрытием job».
    """
    if not _PY.exists():
        pytest.skip(f"нет интерпретатора основной копии: {_PY}")
    _write_chain_scripts(tmp_path)
    argv = [str(_PY), str(tmp_path / "child.py"), str(tmp_path), str(_PY), "exit3"]
    box: dict[str, object] = {}

    def _launch() -> None:
        try:
            box["rc"] = run.default_relaunch(str(_PY), argv)
        except BaseException as exc:  # noqa: BLE001 — исключение потока отдаём тесту
            box["exc"] = exc

    thread = threading.Thread(target=_launch, daemon=True)
    thread.start()
    try:
        assert _poll(
            lambda: (tmp_path / "gc.json").exists() and (tmp_path / "child.json").exists(), _STARTUP_DEADLINE_S
        ), "потомок не поднялся"
        pids = _chain_pids(tmp_path)
        procs = {name: reaper(pids[name]) for name in ("gc", "redir_gc")}
        assert all(p.alive() for p in procs.values()), "потомок мёртв до выхода ребёнка: проверка ничего не значит"

        (tmp_path / "go").write_text("go", encoding="utf-8")
        thread.join(30.0)
        assert not thread.is_alive(), "default_relaunch не вернулся за 30 с"
        assert "exc" not in box, box.get("exc")
        assert box["rc"] == 3

        # Лаунчер (pytest) жив — handle закрыт явно, не выходом процесса.
        assert _poll(lambda: not any(p.alive() for p in procs.values()), _EVENT_DEADLINE_S)
        survivors = [name for name, p in procs.items() if p.alive()]
        assert survivors == [], f"после возврата default_relaunch живы: {survivors}"
    finally:
        (tmp_path / "go").write_text("go", encoding="utf-8")
        thread.join(10.0)
