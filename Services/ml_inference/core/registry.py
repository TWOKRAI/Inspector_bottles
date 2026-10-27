"""ModelRegistry — каталог моделей из папки весов + sidecar-метаданных.

Сканирует директорию: для каждого файла весов (`*.onnx`, `*.pt`, `*.pth`) ищет
одноимённый `*.yaml`-sidecar. Без sidecar модель игнорируется (нет метаданных).

Безопасность: путь `weights` из sidecar резолвится и проверяется на принадлежность
папке моделей (sandbox) — не загружаем произвольный бинарь по `../` или абсолютному пути.

`diagnose(model_id)` (C-55b) — проверка ассетов ОДНОЙ выбранной модели без побочных эффектов:
веса, sidecar, пути из sidecar, файл меток. Выбор файла весов и разбор sidecar общие с `scan()`
(`_weight_files`, `_load_one`), поэтому диагноз и каталог не расходятся.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from multiprocess_framework.modules.logger_module import get_std_logger
from pathlib import Path

import yaml

from Services.ml_inference.core.model_spec import ModelSpec, Normalize

logger = get_std_logger(__name__)

_WEIGHT_SUFFIXES = (".onnx", ".pt", ".pth")
_BACKEND_BY_SUFFIX = {".onnx": "onnx", ".pt": "torch", ".pth": "torch"}

# Белый список id модели. Копия литерала `_NAME_RE` из
# multiprocess_framework/modules/recipe/service.py:142 (имена рецептов): начало и конец — \w,
# внутри буквы/цифры/`_`/`.`/`-`/пробел. Не импортируем: `modules/recipe` — чужой модуль,
# его приватное имя не часть публичного API. Меняется там — сверить здесь.
_MODEL_ID_RE = re.compile(r"\w(?:[\w.\- ]*\w)?")


@dataclass(frozen=True)
class ModelDiagnosis:
    """Итог проверки ассетов модели (`ModelRegistry.diagnose`).

    severity: `error` (модель использовать нельзя), `warning` (модель не выбрана),
    `info` (всё в порядке). message — текст для оператора: без сырого id и без `str(exc)`
    (у pydantic это многострочный ввод). path — файл/каталог, из-за которого находка
    (None — id недопустим, путь строить нельзя). spec — только при `info`.
    """

    severity: Literal["error", "warning", "info"]
    message: str
    path: Path | None
    spec: ModelSpec | None = None


class ModelAssetError(RuntimeError):
    """Тип инцидента «ассеты выбранной модели непригодны» — для `ctx.health.report_error`."""


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

        for stem, weights in self._weight_files().items():
            try:
                spec = self._load_one(weights)
            except FileNotFoundError:
                logger.info(
                    "ModelRegistry: пропуск %s — нет sidecar %s", weights.name, weights.with_suffix(".yaml").name
                )
                continue
            except Exception as exc:  # noqa: BLE001 — каталог не должен падать из-за одной модели
                logger.warning("ModelRegistry: пропуск %s — ошибка sidecar: %s", weights.name, exc)
                continue
            self._specs[stem] = spec
        logger.info("ModelRegistry: найдено моделей: %d (%s)", len(self._specs), self._dir)
        return dict(self._specs)

    def diagnose(self, model_id: str) -> ModelDiagnosis:
        """Проверить ассеты одной модели. Без кэша `_specs` и без побочных эффектов.

        Порядок проверок: пустой id (warning) → допустимость id → каталог → веса → sidecar →
        разбор sidecar → файл весов из sidecar → файл меток → info. Первая найденная проблема
        возвращается сразу. Выбор файла весов — тот же, что у `scan()`.
        """
        root = self._dir
        if model_id == "":
            return ModelDiagnosis("warning", "модель не выбрана — pass-through до выбора в GUI", root)
        if _MODEL_ID_RE.fullmatch(model_id) is None or ".." in model_id:
            # Сырой id в текст не идёт: сообщение уходит в last_error и degraded_reason.
            return ModelDiagnosis(
                "error",
                "недопустимый id модели — разрешены буквы, цифры, подчёркивание, точка, дефис "
                "и пробел внутри имени; две точки подряд запрещены",
                None,
            )
        if not root.is_dir():
            return ModelDiagnosis("error", f"каталог моделей не найден: {root}", root)

        weights = self._weight_files().get(model_id)
        if weights is None:
            suffixes = "|".join(_WEIGHT_SUFFIXES)
            return ModelDiagnosis(
                "error", f"нет весов модели ({model_id} + один из {suffixes}) в {root}", root / model_id
            )

        sidecar = weights.with_suffix(".yaml")
        if not sidecar.is_file():
            return ModelDiagnosis("error", f"нет sidecar {sidecar.name} для модели '{model_id}'", sidecar)
        try:
            spec = self._load_one(weights)
        except Exception as exc:  # noqa: BLE001 — диагноз не падает; str(exc) в текст не идёт
            return ModelDiagnosis("error", f"sidecar {sidecar.name} не читается: {type(exc).__name__}", sidecar)

        if not spec.weights_path.is_file():
            return ModelDiagnosis("error", f"файл весов из sidecar {sidecar.name} не найден", spec.weights_path)
        if spec.labels_path is not None:
            try:
                labels = spec.load_labels()
            except Exception as exc:  # noqa: BLE001 — нечитаемый файл меток — та же находка
                return ModelDiagnosis(
                    "error", f"файл меток из sidecar не читается: {type(exc).__name__}", spec.labels_path
                )
            if labels is None:
                return ModelDiagnosis("error", "файл меток из sidecar отсутствует или пуст", spec.labels_path)
        return ModelDiagnosis(
            "info",
            f"модель '{model_id}': {spec.weights_path.name}, backend {spec.backend}",
            spec.weights_path,
            spec,
        )

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

    def _weight_files(self) -> dict[str, Path]:
        """{стем: файл весов} из папки моделей; общий выбор для `scan()` и `diagnose()`.

        Один проход `sorted(iterdir())`; при `m1.onnx` + `m1.pth` побеждает последний в
        порядке `sorted` (`m1.pth`). Вызывающий проверяет, что папка существует.
        """
        found: dict[str, Path] = {}
        for weights in sorted(self._dir.iterdir()):
            if weights.is_file() and weights.suffix.lower() in _WEIGHT_SUFFIXES:
                found[weights.stem] = weights
        return found

    def _load_one(self, weights: Path) -> ModelSpec:
        """ModelSpec по файлу весов: sidecar `<стем>.yaml` (нет → FileNotFoundError) + разбор."""
        sidecar = weights.with_suffix(".yaml")
        if not sidecar.is_file():
            raise FileNotFoundError(sidecar)
        return self._load_spec(weights, sidecar)

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

        if "input_size" not in raw:
            logger.warning(
                "ModelRegistry: sidecar %s без input_size — использую дефолт (224,224); "
                "укажите input_size явно (размер обучения), иначе препроцесс неверен",
                sidecar.name,
            )
        if "resize_policy" not in raw:
            # Дефолт ModelSpec — letterbox (общая конвенция), но обучение классификации
            # на квадратных кропах обычно идёт через stretch (export пишет его явно).
            # Молчаливый letterbox даст серый паддинг/иной масштаб → тихая порча точности.
            logger.warning(
                "ModelRegistry: sidecar %s без resize_policy — использую дефолт 'letterbox'; "
                "для моделей, обученных stretch (export ml_train), укажите resize_policy явно",
                sidecar.name,
            )

        return ModelSpec(
            name=str(raw.get("name") or weights.stem),
            task=raw.get("task", "classification"),
            backend=raw.get("backend") or _BACKEND_BY_SUFFIX.get(weights.suffix.lower(), "onnx"),
            weights_path=weights_path,
            input_size=raw.get("input_size", (224, 224)),
            layout=raw.get("layout", "NCHW"),
            color=raw.get("color", "RGB"),
            resize_policy=raw.get("resize_policy", "letterbox"),
            normalize=normalize,
            labels_path=labels_path,
            output_name=raw.get("output_name", "logits"),
            angle_head=bool(raw.get("angle_head", False)),
            angle_output_name=raw.get("angle_output_name", "angle"),
            symmetry=raw.get("symmetry") or {},
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
