"""MLTrainService — фасад ml_train для ServiceRegistry (вкладка «Сервисы»).

Обучение запускается CLI/кодом (python -m Services.ml_train train ...);
фасад даёт присутствие в GUI: start() сканирует реестр прогонов,
get_status() — сводка (прогоны, лучший, доступность ML-стека).

ВАЖНО: фасад не импортирует torch (ленивые символы ml_train) — сканер
сервисов не должен тянуть тяжёлый ML-стек при старте приложения.

Discovery: scanner находит файл по имени ``service.py`` и импортирует —
декоратор @register_service регистрирует сервис автоматически.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.service_module import IService, register_service

#: корень репозитория: Services/ml_train/service.py → parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@register_service(name="ml_train")
class MLTrainService:
    """Обучение и выбор моделей: реестр прогонов + готовность ML-стека."""

    name: str = "ml_train"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._summary: list[dict[str, Any]] = []
        self._best: str | None = None
        self._error: str | None = None

    def start(self, config: dict) -> bool:
        """Просканировать реестр прогонов (config['runs_dir'] | data/ml_train/runs)."""
        try:
            from Services.ml_train import RunRegistry  # torch-free символ

            runs_dir = (config or {}).get("runs_dir") or _PROJECT_ROOT / "data" / "ml_train" / "runs"
            registry = RunRegistry(runs_dir)
            registry.scan()
            self._summary = registry.summary()
            best = registry.best()
            self._best = best.name if best is not None else None
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
        """Сводный статус: прогоны, лучший прогон, доступность torch/timm/onnx."""
        data: dict[str, Any] = {
            "state": self.status,
            "service": self.name,
            "runs": len(self._summary),
            "best_run": self._best,
            "ml_stack": {
                "torch": importlib.util.find_spec("torch") is not None,
                "torchvision": importlib.util.find_spec("torchvision") is not None,
                "timm": importlib.util.find_spec("timm") is not None,
                "onnx": importlib.util.find_spec("onnx") is not None,
            },
        }
        if self._error:
            data["error"] = self._error
        return data

    def __repr__(self) -> str:
        return f"MLTrainService(status={self.status!r})"


assert isinstance(MLTrainService(), IService), "MLTrainService не удовлетворяет IService Protocol"
