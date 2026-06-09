"""ModelRegistry — каталог моделей из папки весов + sidecar-метаданных.

Сканирует директорию: для каждого файла весов (`*.onnx`, `*.pt`, `*.pth`) ищет
одноимённый `*.yaml`-sidecar. Без sidecar модель игнорируется (нет метаданных).

Безопасность: путь `weights` из sidecar резолвится и проверяется на принадлежность
папке моделей (sandbox) — не загружаем произвольный бинарь по `../` или абсолютному пути.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from Services.ml_inference.core.model_spec import ModelSpec, Normalize

logger = logging.getLogger(__name__)

_WEIGHT_SUFFIXES = (".onnx", ".pt", ".pth")
_BACKEND_BY_SUFFIX = {".onnx": "onnx", ".pt": "torch", ".pth": "torch"}


class ModelRegistry:
    """Каталог доступных моделей в директории.

    Использование:
        reg = ModelRegistry("data/models")
        reg.scan()
        reg.names()          # → ["mobilenetv3_large", ...]
        spec = reg.get("mobilenetv3_large")
    """

    def __init__(self, models_dir: str | Path) -> None:
        self._dir = Path(models_dir).resolve()
        self._specs: dict[str, ModelSpec] = {}

    @property
    def models_dir(self) -> Path:
        """Корневая папка моделей (resolved)."""
        return self._dir

    def scan(self) -> dict[str, ModelSpec]:
        """Пересканировать папку. Возвращает {model_id: ModelSpec}.

        model_id = basename файла весов без расширения.
        Битые/небезопасные записи пропускаются с warning (не падаем).
        """
        self._specs = {}
        if not self._dir.is_dir():
            logger.warning("ModelRegistry: папка не найдена: %s", self._dir)
            return {}

        for weights in sorted(self._dir.iterdir()):
            if not weights.is_file() or weights.suffix.lower() not in _WEIGHT_SUFFIXES:
                continue
            sidecar = weights.with_suffix(".yaml")
            if not sidecar.is_file():
                logger.info("ModelRegistry: пропуск %s — нет sidecar %s", weights.name, sidecar.name)
                continue
            try:
                spec = self._load_spec(weights, sidecar)
            except Exception as exc:  # noqa: BLE001 — каталог не должен падать из-за одной модели
                logger.warning("ModelRegistry: пропуск %s — ошибка sidecar: %s", weights.name, exc)
                continue
            self._specs[weights.stem] = spec
        logger.info("ModelRegistry: найдено моделей: %d (%s)", len(self._specs), self._dir)
        return dict(self._specs)

    def names(self) -> list[str]:
        """Список model_id (для выпадающего списка GUI)."""
        return list(self._specs.keys())

    def get(self, model_id: str) -> ModelSpec | None:
        """ModelSpec по id или None."""
        return self._specs.get(model_id)

    def items(self) -> dict[str, ModelSpec]:
        """Снимок каталога."""
        return dict(self._specs)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _load_spec(self, weights: Path, sidecar: Path) -> ModelSpec:
        """Распарсить sidecar и собрать ModelSpec с безопасными путями."""
        raw = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("sidecar не является YAML-словарём")

        # Путь к весам: из sidecar (если задан) либо сам файл весов; sandbox-проверка.
        weights_path = self._safe_path(raw.get("weights"), default=weights)

        labels_path: Path | None = None
        if raw.get("labels"):
            labels_path = self._safe_path(raw["labels"], default=None)

        norm_raw = raw.get("normalize") or {}
        normalize = Normalize(**norm_raw) if isinstance(norm_raw, dict) else Normalize()

        return ModelSpec(
            name=str(raw.get("name") or weights.stem),
            task=raw.get("task", "classification"),
            backend=raw.get("backend") or _BACKEND_BY_SUFFIX.get(weights.suffix.lower(), "onnx"),
            weights_path=weights_path,
            input_size=raw.get("input_size", (224, 224)),
            layout=raw.get("layout", "NCHW"),
            color=raw.get("color", "RGB"),
            normalize=normalize,
            labels_path=labels_path,
        )

    def _safe_path(self, value: str | None, default: Path | None) -> Path:
        """Резолв пути относительно папки моделей + проверка sandbox.

        Запрещает выход за пределы `models_dir` (защита от `../` и абсолютных путей).
        """
        if not value:
            if default is None:
                raise ValueError("путь не задан")
            return default
        candidate = (self._dir / value).resolve()
        if not candidate.is_relative_to(self._dir):
            raise ValueError(f"путь вне песочницы data/models: {value}")
        return candidate
