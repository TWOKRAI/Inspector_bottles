"""Реестр активных SHM-сегментов (файл-маркер для Windows cleanup).

На Linux SHM-сегменты живут как файлы в /dev/shm/ — их можно перечислить напрямую.
На Windows нет способа перечислить все SharedMemory объекты в системе, поэтому
используем файл-маркер: при создании SHM имя записывается в JSON-реестр,
при нормальном завершении — удаляется. После kill -9 записи остаются и используются
cleanup-ом для попытки очистки.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ShmRegistry:
    """Реестр активных SHM-сегментов (файл-маркер для Windows cleanup).

    Потокобезопасность: все операции работают с одним JSON-файлом.
    При kill -9 файл остаётся — cleanup использует его при следующем старте.

    Args:
        path: путь к файлу реестра. Передавать явно из конфига приложения.
        logger: ObservableMixin-совместимый объект с методами _log_*.
    """

    def __init__(self, path: Path | str, logger: Any = None) -> None:
        self._path = Path(path)
        self._log = logger

    def _read(self) -> list[str]:
        """Прочитать список имён из файла реестра."""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(n) for n in data]
        except Exception as exc:
            if self._log is not None:
                self._log._log_warning(f"ShmRegistry: не удалось прочитать '{self._path}': {exc}")
        return []

    def _write(self, names: list[str]) -> None:
        """Записать список имён в файл реестра."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            if self._log is not None:
                self._log._log_warning(f"ShmRegistry: не удалось записать '{self._path}': {exc}")

    def register(self, name: str) -> None:
        """Добавить имя SHM в реестр."""
        names = self._read()
        if name not in names:
            names.append(name)
            self._write(names)

    def unregister(self, name: str) -> None:
        """Удалить имя SHM из реестра (при нормальном завершении)."""
        names = self._read()
        if name in names:
            names.remove(name)
            self._write(names)

    def all_names(self) -> list[str]:
        """Получить все зарегистрированные имена SHM."""
        return self._read()

    def clear(self) -> None:
        """Полностью очистить реестр (при нормальном shutdown)."""
        try:
            if self._path.exists():
                self._path.unlink()
        except Exception as exc:
            if self._log is not None:
                self._log._log_warning(f"ShmRegistry: не удалось удалить '{self._path}': {exc}")
