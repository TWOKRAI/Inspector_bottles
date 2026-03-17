#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Утилиты для обхода файловой системы.
"""

from pathlib import Path
from typing import Iterator, List


def iter_files(
    root_dir: Path, extensions: List[str], ignore_dirs: List[str]
) -> Iterator[Path]:
    """
    Рекурсивно обходит root_dir и возвращает пути ко всем файлам,
    чьё расширение входит в extensions, игнорируя папки из ignore_dirs.
    """
    ignore_dirs_set = set(ignore_dirs)
    for path in root_dir.rglob("*"):
        if any(part in ignore_dirs_set for part in path.parts):
            continue
        if path.is_file() and path.suffix in extensions:
            yield path
