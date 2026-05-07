"""CLI для sync-каркаса: python -m scripts.sync [--check] [--only NAME] [--list].

Без флагов — write-режим (обновляет файлы между маркерами).
С --check — проверяет дрифт, печатает unified diff в stderr, exit 1 при расхождении.
С --list — выводит список зарегистрированных sync-модулей.
С --only NAME — применяет только указанный модуль.
"""

from __future__ import annotations

import argparse
import sys

from scripts.sync.registry import SyncModule, apply_sync

# ---------------------------------------------------------------------------
# Регистрация sync-модулей
# ---------------------------------------------------------------------------
# TODO: раскомментировать после реализации T1.3.2–4:
#
# from scripts.sync import adr_modules, adr_toc, adr_obsolete
# SYNC_MODULES: list[SyncModule] = [
#     adr_modules.module(),
#     adr_toc.module(),
#     adr_obsolete.module(),
# ]

SYNC_MODULES: list[SyncModule] = []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.sync",
        description="Синхронизация генерируемых разделов документации.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Проверить дрифт (exit 1 при расхождении), не записывать файлы.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        metavar="NAME",
        help="Применить только указанный sync-модуль (по имени).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        default=False,
        dest="list_modules",
        help="Вывести список зарегистрированных sync-модулей и выйти.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI. Возвращает exit-код."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --list: вывести модули и выйти
    if args.list_modules:
        if not SYNC_MODULES:
            print("(нет зарегистрированных sync-модулей)")
        else:
            for mod in SYNC_MODULES:
                print(f"  {mod.name} — {mod.description}")
        return 0

    # Основной режим: write или check
    exit_code = apply_sync(
        SYNC_MODULES,
        check=args.check,
        only=args.only,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
