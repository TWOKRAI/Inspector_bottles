#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модели данных: FileStats для статистики по файлу.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileStats:
    """Статистика по одному файлу."""

    def __init__(
        self,
        total_lines: int = 0,
        empty_lines: int = 0,
        non_empty_lines: int = 0,
        chars: int = 0,
    ):
        self.total_lines = total_lines
        self.empty_lines = empty_lines
        self.non_empty_lines = non_empty_lines
        self.chars = chars

    @classmethod
    def from_file(cls, file_path: Path) -> "FileStats":
        """Подсчитывает статистику для указанного файла."""
        total = empty = chars = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    total += 1
                    chars += len(line)
                    if line.strip() == "":
                        empty += 1
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"Ошибка чтения {file_path}: {e}")
            return cls(0, 0, 0, 0)

        non_empty = total - empty
        return cls(total, empty, non_empty, chars)

    def to_dict(self) -> dict:
        """Преобразует в словарь для сериализации в JSON."""
        return {
            "total_lines": self.total_lines,
            "empty_lines": self.empty_lines,
            "non_empty_lines": self.non_empty_lines,
            "chars": self.chars,
        }
