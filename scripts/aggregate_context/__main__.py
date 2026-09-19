"""__main__.py — CLI для aggregate_context.

Использование:
    python -m scripts.aggregate_context              # write-режим: обновить root registry
    python -m scripts.aggregate_context --check      # CI: diff + exit 1 при дрифте
    python -m scripts.aggregate_context --list       # список зарегистрированных модулей
    python -m scripts.aggregate_context --only render_context   # один модуль
    python -m scripts.aggregate_context --root .     # альтернативный корень

Дефолтный target — `docs/PROJECT_CONTEXT.md` относительно cwd.
Можно переопределить через `--target path/to/file.md`.

Exit codes:
    0 — всё чисто (или записано)
    1 — обнаружен дрифт (в --check) ИЛИ ошибка (нет маркеров, нет файла)
    2 — некорректные аргументы / target-файл не существует
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .discover import discover_modules
from .registry import SyncModule, apply_sync
from .render_adr import RenderADR
from .render_context import RenderContext

# TODO(Phase B): parse aggregate.toml for extra_excludes, active modules, target override.


def _build_modules(root: Path, target: Path) -> list[SyncModule]:
    """Собирает дефолтный список sync-модулей.

    Discovery вызывается ОДИН раз и расшаривается между рендерерами,
    чтобы не делать `rglob` дважды по большому дереву.

    Порядок render_context раньше render_adr — для приятного чтения diff'а
    при дрифте; apply_sync применяет модули независимо.
    """
    modules = discover_modules(root)
    return [
        RenderContext(root=root, target_file=target, modules=modules),
        RenderADR(root=root, target_file=target, modules=modules),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aggregate_context",
        description="Auto-sync per-module CONTEXT.md / DECISIONS.md → root registry.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI-режим: вывести unified diff и exit 1 при расхождении",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Перечислить зарегистрированные sync-модули и выйти",
    )
    parser.add_argument(
        "--only",
        metavar="NAME",
        help="Применить ровно один sync-модуль (по name)",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Корень проекта (default: cwd)",
    )
    parser.add_argument(
        "--target",
        default="docs/PROJECT_CONTEXT.md",
        help="Целевой root-registry файл (default: docs/PROJECT_CONTEXT.md)",
    )

    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    target = (root / args.target).resolve()

    modules = _build_modules(root=root, target=target)

    if args.list:
        for mod in modules:
            print(f"{mod.name:20s}  {mod.description}")
        return 0

    if not target.exists():
        print(
            f"[ОШИБКА] Target-файл не найден: {target}\n"
            f"Создай его из шаблона: "
            f".claude/plugins/core/templates/PROJECT_CONTEXT.template.md → {args.target}",
            file=sys.stderr,
        )
        return 2

    return apply_sync(modules, check=args.check, only=args.only)


if __name__ == "__main__":
    sys.exit(main())
