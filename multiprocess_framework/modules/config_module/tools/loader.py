"""
ConfigLoader — composable pipeline для сборки Config из нескольких источников.

File I/O делегируется ``DataConverter`` (ADR-CFG-002: нет file I/O в config_module).

Использование::

    from multiprocess_framework.modules.config_module.tools import ConfigLoader

    cfg = (
        ConfigLoader()
        .defaults({"db": {"host": "localhost", "port": 5432}})
        .from_file("config.yaml")
        .from_file("config.local.yaml")
        .from_env(prefix="MYAPP")
        .build()
    )
    print(cfg.get("db.host"))
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

from multiprocess_framework.modules.config_module.tools.merge import deep_merge

if TYPE_CHECKING:
    from pydantic import BaseModel

    from multiprocess_framework.modules.config_module.core.config import Config


class ConfigLoader:
    """
    Composable pipeline: файлы + дефолты + env → Config.

    Слои накладываются в порядке вызовов (позже = выше приоритет).
    ``defaults()`` всегда вставляется первым слоем (самый низкий приоритет).
    """

    def __init__(self) -> None:
        self._layers: List[Dict[str, Any]] = []
        self._defaults: Optional[Dict[str, Any]] = None
        self._env_prefix: Optional[str] = None
        self._schema: Optional[Type["BaseModel"]] = None

    def defaults(self, data: Dict[str, Any]) -> "ConfigLoader":
        """Установить слой дефолтов (самый низкий приоритет)."""
        self._defaults = data
        return self

    def from_dict(self, data: Dict[str, Any]) -> "ConfigLoader":
        """Добавить dict-слой."""
        self._layers.append(data)
        return self

    def from_file(self, path: str | Path, required: bool = False) -> "ConfigLoader":
        """
        Загрузить dict из файла через DataConverter и добавить как слой.

        Если файл не существует и ``required=False`` — пропускается молча.
        Поддерживает: .json, .yaml, .yml (автоопределение по расширению).

        Raises:
            FileNotFoundError: если ``required=True`` и файл не найден.
            ImportError: если DataConverter недоступен.
        """
        file_path = Path(path)

        if not file_path.exists():
            if required:
                raise FileNotFoundError(f"Config file not found: {file_path}")
            return self

        from multiprocess_framework.modules.data_schema_module.serialization.converter import (
            DataConverter,
        )

        data = DataConverter.load_from_file(file_path)
        if isinstance(data, dict):
            self._layers.append(data)

        return self

    def from_env(self, prefix: str) -> "ConfigLoader":
        """
        Установить env_prefix для результирующего Config.

        При ``config.get(key)`` будет проверяться env-переменная
        ``{PREFIX}_{KEY}`` как fallback.
        """
        self._env_prefix = prefix
        return self

    def from_env_dict(self, prefix: str, keys: list[str]) -> "ConfigLoader":
        """
        Собрать dict из env-переменных и добавить как слой.

        Ищет ``{PREFIX}_{KEY}`` для каждого ключа из *keys*.
        Найденные значения добавляются как слой с высоким приоритетом.
        """
        env_data: Dict[str, Any] = {}
        for key in keys:
            env_key = f"{prefix}_{key}".upper().replace(".", "_")
            value = os.environ.get(env_key)
            if value is not None:
                env_data[key] = value
        if env_data:
            self._layers.append(env_data)
        return self

    def validate(self, schema_class: Type["BaseModel"]) -> "ConfigLoader":
        """
        Валидировать объединённые данные через Pydantic schema перед build().

        Raises:
            pydantic.ValidationError: при невалидных данных.
        """
        self._schema = schema_class
        return self

    def build(self) -> "Config":
        """Объединить все слои и вернуть Config объект."""
        from multiprocess_framework.modules.config_module.core.config import Config

        merged = self.build_dict()
        return Config(initial_data=merged, env_prefix=self._env_prefix)

    def build_dict(self) -> Dict[str, Any]:
        """Объединить все слои и вернуть сырой dict."""
        layers: List[Dict[str, Any]] = []

        if self._defaults is not None:
            layers.append(self._defaults)

        layers.extend(self._layers)

        # Merge all layers left-to-right
        result: Dict[str, Any] = {}
        for layer in layers:
            result = deep_merge(result, layer, copy_base=False)

        if self._schema is not None:
            self._schema.model_validate(result)

        return result
