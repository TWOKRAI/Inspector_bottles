#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
file_comments — инструмент для обработки текстовых файлов:
- добавление комментария с путём в начало файла
- подсчёт статистики (строки, символы, пустые/непустые строки)

Поддерживает конфигурацию через JSON-файл с учётом операционной системы.
"""

from .config import Config, ConfigLoader, OSType
from .facade import FileProcessorFacade
from .models import FileStats
from .commenter import PathCommenter
from .stats import FileStatsCounter
from .file_utils import iter_files

__all__ = [
    "Config",
    "ConfigLoader",
    "OSType",
    "FileProcessorFacade",
    "FileStats",
    "PathCommenter",
    "FileStatsCounter",
    "iter_files",
]
