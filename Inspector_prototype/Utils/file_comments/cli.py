#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Интерфейс командной строки.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any

from .config import Config, ConfigLoader
from .facade import FileProcessorFacade
from .models import FileStats

logger = logging.getLogger(__name__)


def setup_parser() -> argparse.ArgumentParser:
    """Настраивает парсер аргументов командной строки с подкомандами."""
    parser = argparse.ArgumentParser(
        description="Обработка файлов: добавление комментария с путём и подсчёт статистики."
    )
    parser.add_argument(
        "--config", "-C", type=Path, help="Путь к JSON-файлу конфигурации"
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Доступные команды"
    )

    # Команда comment
    comment_parser = subparsers.add_parser("comment", help="Добавить комментарии в файлы")
    comment_parser.add_argument("root_dir", type=Path, help="Корневая папка для обхода")
    comment_parser.add_argument(
        "--extensions", "-e", nargs="+", help="Расширения файлов (например .py .md)"
    )
    comment_parser.add_argument(
        "--comment-symbols",
        "-c",
        nargs="+",
        metavar=("EXT", "SYM"),
        help="Пары расширение символ_комментария (например .py '#' .md '<!--')",
    )
    comment_parser.add_argument(
        "--use-absolute",
        "-a",
        action="store_true",
        help="Использовать абсолютные пути (по умолчанию относительные)",
    )
    comment_parser.add_argument(
        "--ignore-dirs",
        "-i",
        nargs="+",
        default=[],
        help="Имена папок, которые нужно игнорировать (например .git __pycache__)",
    )
    comment_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Не изменять файлы, только показать, что будет сделано",
    )

    # Команда stats
    stats_parser = subparsers.add_parser("stats", help="Подсчитать статистику по файлам")
    stats_parser.add_argument("root_dir", type=Path, help="Корневая папка для обхода")
    stats_parser.add_argument(
        "--extensions", "-e", nargs="+", help="Расширения файлов (например .py .md)"
    )
    stats_parser.add_argument(
        "--ignore-dirs",
        "-i",
        nargs="+",
        default=[],
        help="Имена папок, которые нужно игнорировать (например .git __pycache__)",
    )
    stats_parser.add_argument(
        "--output",
        "-o",
        choices=["table", "json"],
        default="table",
        help="Формат вывода статистики (по умолчанию table)",
    )

    # Команда both
    both_parser = subparsers.add_parser(
        "both", help="Сначала добавить комментарии, затем вывести статистику"
    )
    both_parser.add_argument("root_dir", type=Path, help="Корневая папка для обхода")
    both_parser.add_argument(
        "--extensions", "-e", nargs="+", help="Расширения файлов (например .py .md)"
    )
    both_parser.add_argument(
        "--comment-symbols",
        "-c",
        nargs="+",
        metavar=("EXT", "SYM"),
        help="Пары расширение символ_комментария",
    )
    both_parser.add_argument(
        "--use-absolute",
        "-a",
        action="store_true",
        help="Использовать абсолютные пути",
    )
    both_parser.add_argument(
        "--ignore-dirs",
        "-i",
        nargs="+",
        default=[],
        help="Имена папок, которые нужно игнорировать",
    )
    both_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Не изменять файлы (статистика будет по текущему состоянию)",
    )
    both_parser.add_argument(
        "--output",
        "-o",
        choices=["table", "json"],
        default="table",
        help="Формат вывода статистики",
    )

    return parser


def build_config_from_args(args: argparse.Namespace, base_config: Config) -> Config:
    """
    Создаёт конфиг на основе аргументов командной строки,
    объединяя с базовым (из файла).
    """
    cli_config = Config()

    if hasattr(args, "extensions") and args.extensions is not None:
        cli_config.extensions = args.extensions

    if hasattr(args, "comment_symbols") and args.comment_symbols:
        symbols = args.comment_symbols
        if len(symbols) % 2 != 0:
            raise ValueError(
                "comment-symbols должен содержать чётное количество элементов "
                "(пары EXT SYM)"
            )
        cli_config.comment_symbols = {}
        it = iter(symbols)
        for ext, sym in zip(it, it):
            cli_config.comment_symbols[ext] = sym

    if hasattr(args, "use_absolute") and args.use_absolute:
        cli_config.use_absolute_path = True

    if hasattr(args, "ignore_dirs") and args.ignore_dirs:
        cli_config.ignore_dirs = args.ignore_dirs

    return base_config.merge(cli_config)


def print_stats_table(stats: Dict[str, FileStats]) -> None:
    """Выводит статистику в виде таблицы."""
    if not stats:
        print("Нет файлов для отображения.")
        return

    headers = ["Файл", "Всего строк", "Пустых", "Непустых", "Символов"]
    attrs = ["", "total_lines", "empty_lines", "non_empty_lines", "chars"]

    col_widths = []
    for i, (attr, h) in enumerate(zip(attrs, headers)):
        if attr == "":
            max_val = max((len(path) for path in stats.keys()), default=0)
        else:
            max_val = max(
                (len(str(getattr(s, attr))) for s in stats.values()), default=0
            )
        col_widths.append(max(len(h), max_val))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))

    for path, stat in sorted(stats.items()):
        row = [
            path.ljust(col_widths[0]),
            str(stat.total_lines).rjust(col_widths[1]),
            str(stat.empty_lines).rjust(col_widths[2]),
            str(stat.non_empty_lines).rjust(col_widths[3]),
            str(stat.chars).rjust(col_widths[4]),
        ]
        print(" | ".join(row))


def stats_to_dict(stats: Dict[str, FileStats]) -> Dict[str, Dict[str, Any]]:
    """Преобразует статистику в словарь для JSON."""
    return {path: stat.to_dict() for path, stat in stats.items()}


def main() -> None:
    """Точка входа CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = setup_parser()
    args = parser.parse_args()

    if args.config:
        loader = ConfigLoader(args.config)
        base_config = loader.load()
    else:
        base_config = Config()

    try:
        config = build_config_from_args(args, base_config)
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    facade = FileProcessorFacade(args.root_dir, config)

    if args.command == "comment":
        facade.add_comments(dry_run=args.dry_run)

    elif args.command == "stats":
        stats = facade.get_stats()
        if args.output == "json":
            print(json.dumps(stats_to_dict(stats), ensure_ascii=False, indent=2))
        else:
            print_stats_table(stats)

    elif args.command == "both":
        stats = facade.process_all(dry_run=args.dry_run)
        if args.output == "json":
            print(json.dumps(stats_to_dict(stats), ensure_ascii=False, indent=2))
        else:
            print_stats_table(stats)


if __name__ == "__main__":
    main()
