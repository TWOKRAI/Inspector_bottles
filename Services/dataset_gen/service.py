"""DatasetGenService — фасад dataset_gen для ServiceRegistry (вкладка «Сервисы»).

dataset_gen — библиотека (генерация по вызову, без долгоживущего ресурса),
поэтому lifecycle номинальный: start() проверяет готовность движка и каталог
комплектных пресетов, get_status() — сводка для GUI.

Discovery: scanner находит файл по имени ``service.py`` и импортирует —
декоратор @register_service регистрирует сервис автоматически.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import IService, register_service


@register_service(name="dataset_gen")
class DatasetGenService:
    """Генератор синтетических датасетов (cut-and-paste): классы + угол поворота."""

    name: str = "dataset_gen"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._presets: list[str] = []
        self._error: str | None = None

    def start(self, config: dict) -> bool:
        """Проверить готовность: импорт движка + перечень комплектных пресетов."""
        try:
            from Services.dataset_gen import PRESETS_DIR, DatasetEngine  # noqa: F401

            self._presets = sorted(p.name for p in PRESETS_DIR.glob("*.yaml"))
            self._error = None
            self.status = "running"
            return True
        except Exception as exc:  # noqa: BLE001 — статус ошибки уходит в GUI
            self._error = f"{type(exc).__name__}: {exc}"
            self.status = "error"
            return False

    def stop(self) -> bool:
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Сводный статус: состояние + комплектные пресеты."""
        data: dict[str, Any] = {
            "state": self.status,
            "service": self.name,
            "presets": self._presets,
        }
        if self._error:
            data["error"] = self._error
        return data

    def __repr__(self) -> str:
        return f"DatasetGenService(status={self.status!r})"


assert isinstance(DatasetGenService(), IService), "DatasetGenService не удовлетворяет IService Protocol"
