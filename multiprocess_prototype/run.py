#!/usr/bin/env python3
"""multiprocess_prototype launcher — auto-detect проектного .venv.

Логика (venv-guard, ``venv_guard`` — общий для ``frontend/run.py``, одна реализация, C-55a):
  1. Ищем свой ``<корень дерева>/.venv/Scripts/python.exe`` (или ``bin/python``). Есть — git не зовём.
  2. Своего нет (связанный git worktree) — спрашиваем git, где основная копия
     (``git rev-parse --git-common-dir``), и берём ``.venv`` основной копии.
  3. Если найденный python — НЕ текущий интерпретатор — перезапуск через него (скрипт остаётся
     из текущего дерева: код worktree, а не основной копии). POSIX: ``os.execv`` подменяет процесс.
     Windows: ``execv`` лишь эмулируется (новый процесс + немедленный выход с кодом 0), поэтому
     ``default_relaunch`` запускает приложение через ``subprocess.Popen``, ждёт его и отдаёт его код
     выхода (C-70). Windows: приложение запускается приостановленным и кладётся в Job Object
     с ``KILL_ON_JOB_CLOSE`` до первой инструкции: смерть лаунчера (в том числе ``taskkill /F``
     без ``/T``) убивает всё дерево приложения, сирот нет (C-76).
  4. Прямой вызов main.main() (без перезапуска), если интерпретатор уже нужный.

Подсказка «uv sync» печатается только для основной копии без ``.venv``. В связанном worktree
``uv sync`` подсказывать нельзя: он создал бы второй ``.venv`` (с подменой CUDA-сборки torch).
Код выхода при ненайденном venv — 1.

Замечание о sys.path: добавление PROJECT_ROOT — это **намеренный bootstrap
launcher'а**, а не legacy-хак. При прямом запуске (`python multiprocess_prototype/run.py`)
Python кладёт в `sys.path[0]` директорию скрипта, а не корень проекта,
поэтому `from multiprocess_prototype.main import main` иначе не разрешается
без `pip install -e .`. validate.py знает об этом исключении (см. PRODUCTION_DIRS-фильтр).

Ограничение (оно же правило для правки): ``run.py`` исполняется ЛЮБЫМ python до re-exec —
на уровне модуля только stdlib; без синтаксиса 3.12 (``type X = …``, PEP 695, ``match``) и без
``A | B`` вне аннотаций. Аннотации ``Path | None`` допустимы: ``from __future__ import annotations``.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — git rev-parse и перезапуск через Popen: argv списком, без shell
import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
PROJECT_VENV = PROJECT_ROOT / ".venv"


def venv_python(venv_dir: Path) -> Path:
    """Путь к python в venv ``venv_dir``."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _same_interpreter(a: Path, b: Path) -> bool:
    """Проверка что два пути указывают на один и тот же интерпретатор."""
    try:
        return a.resolve() == b.resolve()
    except (OSError, ValueError):
        return False


#: Переменные окружения git, которые перебивают поиск репозитория по cwd.
_GIT_REPO_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def git_common_dir(cwd: Path) -> Path | None:
    """Абсолютный путь общего git-каталога дерева ``cwd`` или ``None``.

    ``None`` значит «основная копия не определена»: git нет на PATH, завис (таймаут),
    ``cwd`` не репозиторий (код 128) или git старше 2.31 (код 129, нет ``--path-format``).
    """
    # Потолок поиска — родитель cwd: git не уйдёт вверх по дереву в чужой репозиторий
    # (на этой машине tmp резолвится в C:/Users/INNOTECH/.git). Корень дерева с `.git`
    # (каталог у основной копии, файл у worktree) git находит и так.
    # Переменные, которыми git выбирает репозиторий в обход cwd (приходят из git hook или
    # `git rebase --exec`), сбрасываем: иначе ответ был бы про чужое дерево.
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV}
    env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    try:
        # Аргументы — литералы, cwd — каталог дерева; таймаут — страховка от зависшего git.
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return Path(out) if out else None


def main_copy_root(
    project_root: Path,
    *,
    common_dir_of: Callable[[Path], Path | None] = git_common_dir,
) -> Path | None:
    """Корень основной копии (родитель общего git-каталога) или ``None``.

    Путь отдаётся как его вернул git, без ``.resolve()``: сравнения делает вызывающий.
    """
    common = common_dir_of(project_root)
    if common is None:
        return None
    return common.parent


def resolve_venv_python(project_root: Path, main_root: Path | None) -> tuple[Path | None, list[Path]]:
    """Первый существующий python из кандидатов: свой, затем основной копии.

    Возвращает ``(python | None, [проверенные кандидаты])``. Чистая функция, без git.
    """
    candidates = [venv_python(project_root / ".venv")]
    if main_root is not None and main_root.resolve() != project_root.resolve():
        candidates.append(venv_python(main_root / ".venv"))
    for index, candidate in enumerate(candidates):
        if candidate.exists():
            # Проверенные — до найденного включительно; хвост после него не смотрели.
            return candidate, candidates[: index + 1]
    return None, candidates


#: CREATE_SUSPENDED: ребёнок создан, но не выполнил ни одной инструкции (C-76).
_CREATE_SUSPENDED = 0x4


def _win_api():
    """Привязки kernel32/ntdll: ``(ctypes, kernel32, ntdll)``. Импорт ctypes — здесь, не на уровне модуля."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    handle = wintypes.HANDLE  # без argtypes 64-битный handle усекается до int
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = handle
    k32.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = handle
    k32.AssignProcessToJobObject.argtypes = [handle, handle]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [handle]
    k32.CloseHandle.restype = wintypes.BOOL
    ntdll.NtResumeProcess.argtypes = [handle]
    ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS: успех = 0
    return ctypes, k32, ntdll


def _job_create() -> int:
    """Job Object с ``KILL_ON_JOB_CLOSE``: закрытие handle убивает всех его членов. ``OSError`` при сбое."""
    ctypes, k32, _ = _win_api()

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("Read", "Write", "Other", "ReadB", "WriteB", "OtherB")]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("Basic", _Basic),
            ("Io", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _Extended()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    # 9 = JobObjectExtendedLimitInformation
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        k32.CloseHandle(job)
        raise ctypes.WinError(error)
    return job


def _proc_open(pid: int) -> int:
    """Handle процесса с правами назначить в job, убить и возобновить (не приватный ``Popen._handle``)."""
    ctypes, k32, _ = _win_api()
    # PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME
    handle = k32.OpenProcess(0x0100 | 0x0001 | 0x0800, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _job_assign(job: int, process: int) -> None:
    ctypes, k32, _ = _win_api()
    if not k32.AssignProcessToJobObject(job, process):
        raise ctypes.WinError(ctypes.get_last_error())


def _proc_resume(process: int) -> None:
    """``NtResumeProcess``: NTSTATUS, успех = 0 (условие читается наоборот)."""
    _, _, ntdll = _win_api()
    status = ntdll.NtResumeProcess(process)
    if status != 0:
        raise OSError(f"NtResumeProcess: NTSTATUS {status & 0xFFFFFFFF:#010x}")


def _handle_close(handle: int | None) -> None:
    """Закрыть handle; ``None`` — ничего. Закрытие handle job убивает всех его членов."""
    if handle:
        _win_api()[1].CloseHandle(handle)


def _start_in_kill_job(exe: str, argv: list[str]) -> subprocess.Popen:
    """Windows: запустить ``argv`` приостановленным, положить в Job Object, возобновить (C-76).

    Ребёнок стартует уже внутри job, поэтому его потомки наследуют job с рождения. Handle job
    остаётся в ``proc._kill_job`` (``None`` — без защиты); закрывает его ``default_relaunch``.
    Сбой создания job или назначения — предупреждение и запуск без защиты (как до C-76); сбой
    ``OpenProcess``/``NtResumeProcess`` или прерывание — ребёнок убит (вечно приостановленный
    процесс хуже сироты), ``OSError`` пробрасывается.
    """
    try:
        job = _job_create()
    except OSError as exc:
        _warn_unprotected(exc)
        return subprocess.Popen(argv, executable=exe)  # nosec B603
    proc = None
    process = None
    try:
        # executable=exe: при argv[0] != exe Windows иначе даёт FileNotFoundError. close_fds по
        # умолчанию: handle job ребёнку не передаётся.
        proc = subprocess.Popen(argv, executable=exe, creationflags=_CREATE_SUSPENDED)  # nosec B603
        process = _proc_open(proc.pid)
        try:
            _job_assign(job, process)
        except OSError as exc:
            _warn_unprotected(exc)
            _handle_close(job)
            job = None
        _proc_resume(process)  # job-ребёнок возобновлён, даже если назначение не удалось
    except BaseException:  # в том числе KeyboardInterrupt между Popen и NtResumeProcess
        if proc is not None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        _handle_close(job)
        raise
    finally:
        _handle_close(process)
    proc._kill_job = job
    return proc


def _warn_unprotected(exc: OSError) -> None:
    print(
        f"[run] ПРЕДУПРЕЖДЕНИЕ: job object недоступен ({exc}); приложение запущено без защиты от сирот", file=sys.stderr
    )


def default_relaunch(exe: str, argv: list[str]) -> int:
    """Перезапустить ``argv`` интерпретатором ``exe`` и вернуть код выхода приложения.

    POSIX: ``os.execv`` подменяет процесс и не возвращается. Windows: ``execv`` — эмуляция
    (родитель сразу выходит с кодом 0, приложение теряется для гейта и TaskStop), поэтому
    запускаем приложение в Job Object (``_start_in_kill_job``) и ждём. stdin/stdout/stderr и
    окружение наследуются. После выхода приложения handle job закрывается: оставшиеся члены
    job (потомки, пережившие приложение) убиваются.
    """
    if os.name != "nt":
        # Аргументы контролируемые (venv-python + скрипт этого дерева + argv)
        os.execv(exe, argv)  # nosec B606
    proc = _start_in_kill_job(exe, argv)  # OSError не ловим
    try:
        while True:
            try:
                rc = proc.wait()
                break
            except KeyboardInterrupt:
                # Ctrl+C в общей консоли получают оба процесса; приложение гасит себя само, а
                # Popen.wait() на Windows сигналом не прерывается — исключение приходит уже ПОСЛЕ
                # выхода ребёнка. Ребёнка не убиваем (subprocess.run сделал бы kill): ждём дальше.
                continue
    finally:
        _handle_close(getattr(proc, "_kill_job", None))
    # Popen.returncode на Windows беззнаковый (0xC0000005 -> 3221225477); возвращаем знаковый.
    return rc - (1 << 32) if rc >= (1 << 31) else rc


def venv_guard(
    script: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    common_dir_of: Callable[[Path], Path | None] = git_common_dir,
    relaunch: Callable[[str, list[str]], int] = default_relaunch,
    tag: str = "[run]",
) -> int | None:
    """Единственная реализация venv-guard: найти venv, при необходимости перезапустить ``script``.

    Возврат: ``None`` — интерпретатор уже нужный, продолжать запуск; любое ``int`` (в том числе
    ``0``) — завершить вход с этим кодом: ``1`` — venv не найден (сообщение в stderr), иначе код
    выхода перезапущенного приложения (``relaunch``). На POSIX настоящий ``default_relaunch``
    через ``os.execv`` не возвращается.
    """
    own = venv_python(project_root / ".venv")
    if own.exists():
        # Свой venv есть — git не нужен.
        venv_py, tried, main_root = own, [own], None
    else:
        main_root = main_copy_root(project_root, common_dir_of=common_dir_of)
        venv_py, tried = resolve_venv_python(project_root, main_root)

    if venv_py is None:
        lines = [f"{tag} ОШИБКА: venv не найден. Проверено:"]
        lines += [f"       {path}" for path in tried]
        if main_root is None:
            lines.append("       основная копия не определена: `git rev-parse --git-common-dir` не ответил")
        elif main_root.resolve() == project_root.resolve():
            # Основная копия без .venv — единственный случай, где `uv sync` уместен.
            lines.append(f"       Создай его: cd {project_root} && uv sync")
        else:
            lines.append(f"       venv основной копии {main_root} тоже не найден")
        print("\n".join(lines), file=sys.stderr)
        return 1

    # Re-exec через найденный Python, если сейчас другой интерпретатор
    if not _same_interpreter(Path(sys.executable), venv_py):
        note = f" (venv основной копии {main_root})" if venv_py != own else ""
        print(f"{tag} переключаюсь на {venv_py}{note}", file=sys.stderr)
        return relaunch(str(venv_py), [str(venv_py), str(script.resolve()), *sys.argv[1:]])
    return None


def launch(
    *,
    project_root: Path = PROJECT_ROOT,
    common_dir_of: Callable[[Path], Path | None] = git_common_dir,
    relaunch: Callable[[str, list[str]], int] = default_relaunch,
) -> int:
    """venv-guard: переключиться на проектный .venv и передать управление приложению."""
    rc = venv_guard(
        Path(__file__), project_root=project_root, common_dir_of=common_dir_of, relaunch=relaunch, tag="[run]"
    )
    if rc is not None:
        return rc

    # Уже в нужном venv — добавляем корень проекта в sys.path. Именно константа PROJECT_ROOT,
    # не параметр project_root: в sys.path идёт корень дерева, чей код исполняется сейчас.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from multiprocess_prototype.main import main as app_main

    # --headless (Ф2 T2.2): явный backend-only флаг основного входа — вырезаем его
    # из argv ДО извлечения позиционного pipeline-override, чтобы он не был принят
    # за имя рецепта. Отсутствие флага не значит "не headless" — main() сам смотрит
    # env INSPECTOR_HEADLESS, если explicit-флаг не передан (см. main._is_headless).
    argv = sys.argv[1:]
    headless_flag = "--headless" in argv
    if headless_flag:
        argv = [a for a in argv if a != "--headless"]

    return app_main(argv[0] if argv else None, headless=True if headless_flag else None)


if __name__ == "__main__":
    sys.exit(launch())
