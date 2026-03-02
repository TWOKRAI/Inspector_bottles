# -*- coding: utf-8 -*-
"""
FileStorage — хранилище регистров в JSON-файлах.

Реализует интерфейс IRegisterStorage для персистентности без базы данных.
Готова к замене на SQLiteStorage, RedisStorage или PostgreSQLStorage —
достаточно реализовать те же методы: load / save / exists / delete.

Пример использования:

    from multiprocess_framework.refactored.modules.data_schema_module import (
        FileStorage, RegistersManager,
    )

    rm = RegistersManager()
    storage = FileStorage("data/registers")

    # Сохранение
    rm.save(storage, "main_process")

    # Загрузка (например, при следующем запуске)
    loaded = rm.load(storage, "main_process")
    print(loaded)  # → True если файл существует

Для подключения других бэкендов — реализуйте IRegisterStorage:

    class RedisStorage:
        def load(self, container_name: str) -> dict: ...
        def save(self, container_name: str, data: dict) -> None: ...
        def exists(self, container_name: str) -> bool: ...
        def delete(self, container_name: str) -> bool: ...
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FileStorage:
    """
    Хранилище RegistersContainer в JSON-файлах.

    Каждый контейнер сохраняется в отдельный файл:
        base_path / {container_name}.json
    """

    def __init__(self, base_path: str | Path = "data") -> None:
        """
        Args:
            base_path: Директория для хранения файлов.
                       Создаётся автоматически если не существует.
        """
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        """Путь к файлу контейнера."""
        return self._base / f"{name}.json"

    def load(self, container_name: str) -> dict[str, Any]:
        """
        Загрузить данные из JSON-файла.

        Возвращает пустой dict если файл не существует.
        """
        p = self._path(container_name)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, container_name: str, data: dict[str, Any]) -> None:
        """Сохранить данные в JSON-файл (создаёт или перезаписывает)."""
        self._path(container_name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def exists(self, container_name: str) -> bool:
        """Проверить наличие сохранённых данных."""
        return self._path(container_name).exists()

    def delete(self, container_name: str) -> bool:
        """Удалить данные. Возвращает True если файл существовал."""
        p = self._path(container_name)
        if p.exists():
            p.unlink()
            return True
        return False

    def list_containers(self) -> list[str]:
        """Список имён всех сохранённых контейнеров."""
        return [p.stem for p in self._base.glob("*.json")]
