#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль конфигурации: типы ОС, модель Config и загрузчик из JSON.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OSType:
    """Операционные системы, поддерживаемые детектором."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "darwin"
    UNKNOWN = "unknown"

    @classmethod
    def detect(cls) -> str:
        """Определяет текущую ОС по sys.platform."""
        system = sys.platform.lower()
        if system.startswith("win"):
            return cls.WINDOWS
        if system.startswith("linux"):
            return cls.LINUX
        if system.startswith("darwin"):
            return cls.MACOS
        return cls.UNKNOWN


class Config:
    """Модель конфигурации приложения."""

    def __init__(
        self,
        extensions: List[str] | None = None,
        comment_symbols: Dict[str, str] | None = None,
        use_absolute_path: bool = False,
        ignore_dirs: List[str] | None = None,
        path_base: Optional[Path] = None,
    ):
        self.extensions = extensions or [".py", ".md"]
        self.comment_symbols = comment_symbols or {}
        self.use_absolute_path = use_absolute_path or False
        self.ignore_dirs = ignore_dirs or []
        self.path_base = path_base.resolve() if path_base else None

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Создаёт экземпляр Config из словаря (результата загрузки JSON)."""
        path_base = data.get("path_base")
        if path_base is not None:
            path_base = Path(path_base) if isinstance(path_base, str) else path_base
        return cls(
            extensions=data.get("extensions", [".py", ".md"]),
            comment_symbols=data.get("comment_symbols", {}),
            use_absolute_path=data.get("use_absolute_path", False),
            ignore_dirs=data.get("ignore_dirs", []),
            path_base=path_base,
        )

    def merge(self, other: "Config") -> "Config":
        """
        Объединяет два конфига. Значения из other имеют приоритет.
        """
        new_extensions = other.extensions if other.extensions else self.extensions
        new_comment_symbols = {**self.comment_symbols, **other.comment_symbols}
        new_use_absolute_path = other.use_absolute_path
        new_ignore_dirs = list(set(self.ignore_dirs + other.ignore_dirs))
        new_path_base = other.path_base if other.path_base is not None else self.path_base

        return Config(
            extensions=new_extensions,
            comment_symbols=new_comment_symbols,
            use_absolute_path=new_use_absolute_path,
            ignore_dirs=new_ignore_dirs,
            path_base=new_path_base,
        )


class ConfigLoader:
    """Загрузчик конфигурации из JSON-файла с учётом ОС."""

    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> Config:
        """Загружает и объединяет секции default и ОС-специфичную."""
        if not self.config_path.exists():
            logger.warning(
                f"Файл конфигурации {self.config_path} не найден. "
                "Используются значения по умолчанию."
            )
            return Config()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                f"Ошибка загрузки конфигурации: {e}. "
                "Используются значения по умолчанию."
            )
            return Config()

        default_data = raw.get("default", {})
        config = Config.from_dict(default_data)

        current_os = OSType.detect()
        os_data = raw.get(current_os, {})
        if os_data:
            os_config = Config.from_dict(os_data)
            config = config.merge(os_config)

        return config
