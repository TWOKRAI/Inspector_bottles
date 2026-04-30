#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Фасад, объединяющий комментирование и подсчёт статистики.
"""

from pathlib import Path
from typing import Dict, List

from .commenter import PathCommenter
from .config import Config
from .models import FileStats
from .stats import FileStatsCounter


class FileProcessorFacade:
    """Фасад с общей конфигурацией для комментирования и статистики."""

    def __init__(self, root_dir: Path, config: Config):
        self.root_dir = root_dir.resolve()
        self.config = config
        self.commenter = PathCommenter(root_dir, config)
        self.counter = FileStatsCounter(root_dir, config)

    def add_comments(self, dry_run: bool = False) -> List[Path]:
        """Добавляет комментарии с путём в начало файлов."""
        return self.commenter.process(dry_run)

    def get_stats(self) -> Dict[str, FileStats]:
        """Возвращает статистику по файлам."""
        return self.counter.count()

    def process_all(self, dry_run: bool = False) -> Dict[str, FileStats]:
        """
        Выполняет обе операции: сначала добавляет комментарии,
        затем возвращает статистику (уже после изменений).
        """
        self.add_comments(dry_run)
        return self.get_stats()
