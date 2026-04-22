#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль подсчёта статистики по файлам.
"""

from pathlib import Path
from typing import Dict

from .config import Config
from .file_utils import iter_files
from .models import FileStats


class FileStatsCounter:
    """Собирает статистику по группе файлов."""

    def __init__(self, root_dir: Path, config: Config):
        self.root_dir = root_dir.resolve()
        self.config = config

    def count(self) -> Dict[str, FileStats]:
        """
        Возвращает словарь {относительный_путь: FileStats} для всех файлов,
        соответствующих расширениям.
        """
        stats = {}
        for file_path in iter_files(
            self.root_dir, self.config.extensions, self.config.ignore_dirs
        ):
            rel_path = str(file_path.relative_to(self.root_dir))
            stats[rel_path] = FileStats.from_file(file_path)
        return stats
