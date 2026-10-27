#!/usr/bin/env python3
"""multiprocess_prototype launcher — auto-detect проектного .venv.

Логика (venv-guard, ``venv_guard`` — общий для ``frontend/run.py``, одна реализация, C-55a):
  1. Ищем свой ``<корень дерева>/.venv/Scripts/python.exe`` (или ``bin/python``). Есть — git не зовём.
  2. Своего нет (связанный git worktree) — спрашиваем git, где основная копия
     (``git rev-parse --git-common-dir``), и берём ``.venv`` основной копии.
  3. Если найденный python — НЕ текущий интерпретатор — re-exec через него (скрипт остаётся
     из текущего дерева: код worktree, а не основной копии).
  4. Прямой вызов main.main() (без subprocess).

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
import subprocess  # nosec B404 — единственный вызов: git rev-parse, argv литеральный, без shell
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


def git_common_dir(cwd: Path) -> Path | None:
    """Абсолютный путь общего git-каталога дерева ``cwd`` или ``None``.

    ``None`` значит «основная копия не определена»: git нет на PATH, завис (таймаут),
    ``cwd`` не репозиторий (код 128) или git старше 2.31 (код 129, нет ``--path-format``).
    """
    # Потолок поиска — родитель cwd: git не уйдёт вверх по дереву в чужой репозиторий
    # (на этой машине tmp резолвится в C:/Users/INNOTECH/.git). Корень дерева с `.git`
    # (каталог у основной копии, файл у worktree) git находит и так.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
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


def venv_guard(
    script: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    common_dir_of: Callable[[Path], Path | None] = git_common_dir,
    execv: Callable[..., object] = os.execv,
    tag: str = "[run]",
) -> int | None:
    """Единственная реализация venv-guard: найти venv, при необходимости re-exec ``script``.

    Возврат: ``1`` — venv не найден (сообщение в stderr); ``None`` — текущий интерпретатор
    уже нужный, продолжать запуск. Настоящий ``os.execv`` не возвращается.
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
        # Re-exec в venv — аргументы контролируемые (venv-python + скрипт этого дерева + argv)
        execv(str(venv_py), [str(venv_py), str(script.resolve()), *sys.argv[1:]])  # nosec B606
    return None


def launch(
    *,
    project_root: Path = PROJECT_ROOT,
    common_dir_of: Callable[[Path], Path | None] = git_common_dir,
    execv: Callable[..., object] = os.execv,
) -> int:
    """venv-guard: переключиться на проектный .venv и передать управление приложению."""
    rc = venv_guard(Path(__file__), project_root=project_root, common_dir_of=common_dir_of, execv=execv, tag="[run]")
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
