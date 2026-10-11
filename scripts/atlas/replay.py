"""Повтор одной команды из строки факта брифа (Task 1.9c): allow-list, без shell, дерево процессов убивается.

Purpose: `lint_brief` сверяет литерал строки FACTS/ACCEPTANCE с выводом команды; этот модуль решает, можно ли команду
    запускать (`python -m scripts.atlas <pack|card|ref|log|brief|index>`, `python -m pytest --collect-only`, чтение
    `git`, `wc -l`), и запускает её с корнем репозитория как cwd. Команда вне списка не запускается: `run` -> None.
    Запуск без shell, `stdin` закрыт (команда не ждёт ввода), stdout и stderr — один поток.
Public API: Replay, run.
Stability: lite
    Исключение из правила PEP 695: синтаксис не выше Python 3.11 — модуль грузит хук `lint-brief.sh` под `$PY`,
    который может быть старше `.venv`.
"""

from __future__ import annotations

import math
import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Replay", "run"]

_DEFAULT_TIMEOUT = 300.0
_READ_AFTER_KILL = 5.0  # вывод после убийства читаем с границей: внук мог держать канал
_PKG_ROOT = Path(__file__).resolve().parents[2]  # каталог пакета `scripts` запущенного Атласа

_ATLAS_VIEWS = {"pack", "card", "ref", "log", "brief", "index"}
_GIT_READ = {"grep", "log", "diff", "cat-file", "rev-parse", "ls-files", "ls-tree", "show"}
_GIT_BAD_LONG = (
    "--output",
    "--open-files-in-pager",
    "--exec",
    "--batch",
    "--ext-diff",
    "--textconv",
    "--follow-symlinks",
)
_PYTEST_FLAGS = {"-q", "--collect-only"}


@dataclass(frozen=True)
class Replay:
    """Итог запуска: код возврата, stdout+stderr (UTF-8, LF), признак таймаута."""

    code: int
    out: str
    timed_out: bool


def _timeout(value: float | None) -> float:
    if value is not None:
        return value
    try:
        seconds = float(os.environ.get("ATLAS_REPLAY_TIMEOUT", ""))
    except (ValueError, OverflowError):
        return _DEFAULT_TIMEOUT
    return seconds if math.isfinite(seconds) and seconds > 0 else _DEFAULT_TIMEOUT


def _atlas_ok(args: list[str]) -> bool:
    if not args or args[0] not in _ATLAS_VIEWS:
        return False
    return not (args[0] in ("brief", "index") and any(a.startswith("--w") for a in args))  # --write и сокращения


def _pytest_ok(args: list[str]) -> bool:
    if "--collect-only" not in args:
        return False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-k", "-m"):
            i += 1
            if i >= len(args):
                return False
        elif arg == "-p":
            i += 1
            if i >= len(args) or not args[i].startswith("no:"):
                return False
        elif arg.startswith("@") or (arg.startswith("-") and arg not in _PYTEST_FLAGS):  # @файл — argfile pytest
            return False
        i += 1
    return True


def _git_ok(args: list[str]) -> bool:
    if not args or args[0] not in _GIT_READ:
        return False  # `git -c …` и прочие глобальные опции — вне списка
    for arg in args[1:]:
        if arg == "--":  # дальше — пути, не опции
            break
        name = arg.split("=")[0]
        if name.startswith("--"):  # само имя или его сокращение: `--op=…` — это `--open-files-in-pager`
            if len(name) > 2 and any(bad.startswith(name) or name.startswith(bad) for bad in _GIT_BAD_LONG):
                return False
        elif arg.startswith("-") and "O" in arg:  # склейка коротких: `-nOtouch`
            return False
    return True


def _allowed(argv: list[str]) -> bool:
    if argv[0] in ("python", "python3") and argv[1:3] == ["-m", "scripts.atlas"]:
        return _atlas_ok(argv[3:])
    if argv[0] in ("python", "python3") and argv[1:3] == ["-m", "pytest"]:
        return _pytest_ok(argv[3:])
    return argv[0] == "git" and _git_ok(argv[1:])


def _wc(root: Path, paths: list[str]) -> Replay | None:
    """`wc -l <путь>…` в процессе: число `\\n` в байтах файла; файл вне корня или каталог — вне списка."""
    base, lines, total = root.resolve(), [], 0
    for rel in paths:
        target = (root / rel).resolve()
        if (base != target and base not in target.parents) or target.is_dir():
            return None
        if not target.is_file():
            return Replay(1, f"wc: {rel}: No such file or directory\n", False)
        count = target.read_bytes().count(b"\n")
        total += count
        lines.append(f"{count} {rel}")
    if len(lines) > 1:
        lines.append(f"{total} total")
    return Replay(0, "\n".join(lines) + "\n", False)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15, check=False
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.kill()  # запасной путь: хотя бы сам процесс


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", "replace").replace("\r\n", "\n")


def _spawn(root: Path, argv: list[str], timeout: float) -> Replay:
    old = os.environ.get("PYTHONPATH")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(_PKG_ROOT) + (os.pathsep + old if old else "")}
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **group,  # type: ignore[arg-type]
        )
    except OSError as exc:
        return Replay(127, f"{exc}\n", False)
    try:
        raw, _ = proc.communicate(timeout=timeout)
        return Replay(proc.returncode, _decode(raw), False)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
    try:
        raw, _ = proc.communicate(timeout=_READ_AFTER_KILL)
    except subprocess.TimeoutExpired:
        raw = b""
    return Replay(proc.returncode if proc.returncode is not None else -9, _decode(raw), True)


def run(root: Path, cmd: str, timeout: float | None = None) -> Replay | None:
    """Выполнить `cmd` из корня `root`; None — команды нет в allow-list (или она не разбирается), не запущена."""
    try:
        argv = shlex.split(cmd)  # POSIX: `\\` съедается, в брифах пути через `/`
    except ValueError:
        return None
    if not argv:
        return None
    if argv[:2] == ["wc", "-l"] and len(argv) > 2:
        return _wc(root, argv[2:])
    if not _allowed(argv):
        return None
    if argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return _spawn(root, argv, _timeout(timeout))
