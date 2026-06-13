"""ModelSpec — описание модели (sidecar-метаданные) для data-driven инференса.

Sidecar `<basename>.yaml` рядом с весами описывает ВСЁ, что нужно для препроцессинга
и постобработки: размер входа, layout (NCHW/NHWC), порядок каналов, нормализацию,
backend и метки. Благодаря этому добавление новой модели не требует правок кода.

Слой Services → framework (Pydantic v2). Dict-at-boundary: `from_sidecar`/`to_dict`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TaskType = Literal["classification", "detection"]
BackendType = Literal["onnx", "torch"]
LayoutType = Literal["NCHW", "NHWC"]
ColorOrder = Literal["RGB", "BGR"]
ResizePolicy = Literal["letterbox", "stretch", "center_crop"]
SymmetryType = Literal["none", "180", "full"]


class Normalize(BaseModel):
    """Параметры нормализации входа: (pixel/255 - mean) / std (поканально)."""

    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)


class ModelSpec(BaseModel):
    """Полное описание модели для движка инференса.

    Поле `weights_path` — абсолютный путь к весам (резолвится registry с проверкой
    sandbox). Поле `labels_path` — абсолютный путь к файлу меток (опц.).
    """

    name: str
    task: TaskType = "classification"
    backend: BackendType = "onnx"
    weights_path: Path
    input_size: tuple[int, int] = (224, 224)  # (H, W)
    layout: LayoutType = "NCHW"
    color: ColorOrder = "RGB"
    resize_policy: ResizePolicy = "letterbox"
    normalize: Normalize = Field(default_factory=Normalize)
    labels_path: Path | None = None

    # --- мультиголовость: классификация + регрессия угла -----------------
    output_name: str = "logits"  # имя выхода-классификатора
    angle_head: bool = False  # есть ли голова угла (sin, cos)
    angle_output_name: str = "angle"  # имя выхода угла
    #: симметрия класса для декода угла: {class_name: none|180|full}
    symmetry: dict[str, SymmetryType] = Field(default_factory=dict)

    @field_validator("input_size", mode="before")
    @classmethod
    def _coerce_input_size(cls, v: Any) -> Any:
        """Принять list/tuple из YAML; одно число → квадрат."""
        if isinstance(v, int):
            return (v, v)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return (int(v[0]), int(v[1]))
        return v

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (пути → str)."""
        d = self.model_dump()
        d["weights_path"] = str(self.weights_path)
        d["labels_path"] = str(self.labels_path) if self.labels_path else None
        return d

    def load_labels(self) -> list[str] | None:
        """Прочитать метки из labels_path (по строке на класс). None если файла нет."""
        if self.labels_path is None or not self.labels_path.is_file():
            return None
        text = self.labels_path.read_text(encoding="utf-8")
        labels = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return labels or None
