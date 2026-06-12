"""ml_train — универсальный сервис обучения и выбора моделей.

Публичный API:
    TrainConfig            — декларативный конфиг прогона (YAML/dict)
    RunRegistry, RunInfo   — каталог прогонов, сравнение, выбор лучшего
    Trainer, train         — обучение (требует torch; ленивый импорт)
    build_model            — сборка модели по конфигу (torch)
    build_dataloaders      — данные по конфигу (torch)
    export_onnx            — экспорт чекпоинта в ONNX + sidecar ml_inference (torch)
    available_archs        — список архитектур и их источников
    PRESETS_DIR            — комплектные пресеты конфигов

torch-зависимые символы импортируются лениво: конфиги и реестр прогонов
доступны в окружении без ML-стека (GUI-процесс, CI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Services.ml_train.config import TrainConfig
from Services.ml_train.selection import RunInfo, RunRegistry

PRESETS_DIR = Path(__file__).parent / "presets"

_LAZY = {
    "Trainer": ("Services.ml_train.trainer", "Trainer"),
    "TrainResult": ("Services.ml_train.trainer", "TrainResult"),
    "train": ("Services.ml_train.trainer", "train"),
    "build_model": ("Services.ml_train.models", "build_model"),
    "available_archs": ("Services.ml_train.models", "available_archs"),
    "MultiHeadModel": ("Services.ml_train.models", "MultiHeadModel"),
    "build_dataloaders": ("Services.ml_train.data", "build_dataloaders"),
    "ExportedDataset": ("Services.ml_train.data", "ExportedDataset"),
    "FolderDataset": ("Services.ml_train.data", "FolderDataset"),
    "export_onnx": ("Services.ml_train.export", "export_onnx"),
    "load_checkpoint": ("Services.ml_train.export", "load_checkpoint"),
}

__all__ = [
    "TrainConfig",
    "RunInfo",
    "RunRegistry",
    "PRESETS_DIR",
    *list(_LAZY),
]


def __getattr__(name: str) -> Any:
    """Ленивый импорт torch-зависимых символов (torch не обязателен для конфигов/реестра)."""
    if name in _LAZY:
        import importlib

        module_name, attr = _LAZY[name]
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ImportError(f"{name} требует ML-стек: pip install '.[ml-train]' (torch, torchvision, timm)") from exc
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
