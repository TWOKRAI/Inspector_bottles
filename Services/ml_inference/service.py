"""MLInferenceService — фасад ml_inference для ServiceRegistry (вкладка «Сервисы»).

Инференс живёт в pipeline-плагине ``ml_inference``; фасад даёт присутствие
сервиса в GUI: start() сканирует каталог моделей (data/models), get_status() —
список доступных моделей и наличие backend-библиотек.

Discovery: scanner находит файл по имени ``service.py`` и импортирует —
декоратор @register_service регистрирует сервис автоматически.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.service_module import IService, register_service

#: корень репозитория: Services/ml_inference/service.py → parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@register_service(name="ml_inference")
class MLInferenceService:
    """Каталог моделей инференса (data/models) + статус ML-backend'ов."""

    name: str = "ml_inference"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._models: list[str] = []
        self._error: str | None = None

    def start(self, config: dict) -> bool:
        """Просканировать каталог моделей (config['models_dir'] | data/models)."""
        try:
            from Services.ml_inference.core.registry import ModelRegistry

            models_dir = (config or {}).get("models_dir") or _PROJECT_ROOT / "data" / "models"
            registry = ModelRegistry(models_dir)
            self._models = sorted(registry.scan().keys())
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
        """Сводный статус: модели каталога + доступность backend-библиотек."""
        data: dict[str, Any] = {
            "state": self.status,
            "service": self.name,
            "models": self._models,
            "backends": {
                "onnxruntime": importlib.util.find_spec("onnxruntime") is not None,
                "torch": importlib.util.find_spec("torch") is not None,
            },
        }
        if self._error:
            data["error"] = self._error
        return data

    def __repr__(self) -> str:
        return f"MLInferenceService(status={self.status!r})"


assert isinstance(MLInferenceService(), IService), "MLInferenceService не удовлетворяет IService Protocol"
