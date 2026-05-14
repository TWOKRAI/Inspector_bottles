# -*- coding: utf-8 -*-
"""
FileStatsChannel — канал записи метрик в JSON/CSV файл.
"""

import json
from pathlib import Path
from typing import Any, Dict

from ...channel_routing_module.interfaces import IChannel


class FileStatsChannel(IChannel):
    """Канал записи метрик в файл (JSON)."""

    def __init__(
        self,
        file_path: str,
        format: str = "json",
        name: str = "file_stats",
    ) -> None:
        """
        Args:
            file_path: Путь к файлу
            format: "json" или "csv"
            name: Имя канала
        """
        self._path = Path(file_path)
        self._format = format.lower()
        self._name = name
        self._file = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "file"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Записать снапшот в файл."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)

            if self._format == "json":
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
            else:
                # CSV: одна строка на снапшот
                with open(self._path, "a", encoding="utf-8") as f:
                    ts = data.get("timestamp", 0)
                    count = data.get("total_count", 0)
                    metrics = data.get("metrics", [])
                    line = f"{ts},{count},{json.dumps(metrics)}\n"
                    f.write(line)

            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        """Закрыть канал."""
        self._file = None

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.channel_type,
            "path": str(self._path),
            "format": self._format,
            "active": True,
        }
