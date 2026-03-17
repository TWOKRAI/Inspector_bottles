#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль добавления комментариев с путём в начало файлов.
"""

import logging
from pathlib import Path
from typing import List

from .config import Config
from .file_utils import iter_files

logger = logging.getLogger(__name__)


class PathCommenter:
    """Добавляет комментарий с путём в начало файлов указанных расширений."""

    def __init__(self, root_dir: Path, config: Config):
        self.root_dir = root_dir.resolve()
        self.config = config

    def process(self, dry_run: bool = False) -> List[Path]:
        """
        Обходит файлы и добавляет комментарий.
        Возвращает список обработанных файлов.
        """
        processed = []
        for file_path in iter_files(
            self.root_dir, self.config.extensions, self.config.ignore_dirs
        ):
            self._add_comment(file_path, dry_run)
            processed.append(file_path)
        return processed

    def _add_comment(self, file_path: Path, dry_run: bool) -> None:
        """Добавляет комментарий в начало одного файла."""
        if self.config.use_absolute_path:
            path_to_insert = str(file_path.resolve())
        else:
            path_to_insert = str(file_path.relative_to(self.root_dir))

        comment_symbol = self.config.comment_symbols.get(file_path.suffix, "#")
        comment_line = f"{comment_symbol} {path_to_insert}\n"

        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"Не удалось прочитать {file_path}: {e}")
            return

        if content.startswith(comment_line):
            logger.info(f"Пропуск {file_path} (уже содержит комментарий)")
            return

        new_content = comment_line + content

        if dry_run:
            logger.info(
                f"[DRY RUN] В {file_path} будет добавлен комментарий: "
                f"{comment_line.rstrip()}"
            )
        else:
            try:
                file_path.write_text(new_content, encoding="utf-8")
                logger.info(f"Обработан {file_path}")
            except OSError as e:
                logger.error(f"Ошибка записи {file_path}: {e}")
