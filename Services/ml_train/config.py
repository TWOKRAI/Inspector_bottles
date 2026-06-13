"""TrainConfig — декларативный конфиг обучения (Pydantic v2).

Dict-at-boundary: `from_yaml` / `from_dict` / `to_dict`. Конфиг полностью
описывает прогон: модель, данные, оптимизация, режим обучения, экспорт —
один YAML = воспроизводимый эксперимент.

Импортируется БЕЗ torch (валидация конфигов доступна в любом окружении).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

DataSource = Literal["synthetic", "exported", "folder"]
SchedulerType = Literal["cosine", "plateau", "none"]
AmpMode = Literal["auto", "off", "fp16", "bf16"]
MonitorMetric = Literal["balanced_accuracy", "accuracy", "val_loss", "angle_mae_deg"]

#: метрики, у которых «лучше» = меньше (режим монитора, сортировка RunRegistry)
MINIMIZE_METRICS = {"val_loss", "angle_mae_deg"}


class ModelConfig(BaseModel):
    """Архитектура и головы.

    arch: имя из реестра (`mobilenet_v3_large`, `mobilenet_v3_small`,
    `mobilenetv4_small|medium|large|hybrid_medium`) либо `timm/<имя>` —
    любая архитектура timm (универсальный passthrough).
    """

    arch: str = "mobilenet_v3_large"
    pretrained: bool = True
    num_classes: int | None = None  # None → определяется из данных
    dropout: float = Field(default=0.2, ge=0.0, lt=1.0)
    angle_head: bool = False  # + регрессия угла (sin, cos) с маской angle_valid


class NormalizeConfig(BaseModel):
    """Нормализация входа: (pixel/255 - mean) / std. Совпадает с sidecar ml_inference."""

    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)


class AugmentConfig(BaseModel):
    """Аугментации на тензорах (для exported/folder; синтетика аугментирована движком).

    hflip по умолчанию ВЫКЛ: для текста/букв зеркалирование меняет класс.
    """

    enabled: bool = True
    hflip: bool = False
    rotation_deg: float = Field(default=0.0, ge=0.0, le=180.0)
    color_jitter: float = Field(default=0.1, ge=0.0, le=0.5)  # brightness/contrast/saturation
    random_erasing: float = Field(default=0.0, ge=0.0, le=1.0)  # вероятность


class DataConfig(BaseModel):
    """Источник данных и DataLoader.

    - synthetic: generator_preset (YAML GeneratorConfig dataset_gen), генерация на лету
    - exported: root с train/val[/test] (export_splits) либо один набор с labels.csv
    - folder: root с подпапками-классами (Good/Bad/Neutral; вложенность допустима)
    """

    source: DataSource = "synthetic"
    generator_preset: str | None = None
    samples_per_epoch: int = Field(default=6600, ge=1)  # synthetic: train-сэмплов на эпоху
    val_samples: int = Field(default=990, ge=1)  # synthetic: объём валидации
    root: str | None = None  # exported/folder
    val_split: float = Field(default=0.15, gt=0.0, lt=1.0)  # если нет готового val
    image_size: tuple[int, int] = (128, 128)  # (H, W); exported/folder ресайзятся
    batch_size: int = Field(default=64, ge=1)
    num_workers: int = Field(default=0, ge=0)
    seed: int = 42
    normalize: NormalizeConfig = Field(default_factory=NormalizeConfig)
    augment: AugmentConfig = Field(default_factory=AugmentConfig)

    @model_validator(mode="after")
    def _check_source_args(self) -> DataConfig:
        if self.source == "synthetic" and not self.generator_preset:
            raise ValueError("data.source=synthetic требует data.generator_preset (YAML dataset_gen)")
        if self.source in ("exported", "folder") and not self.root:
            raise ValueError(f"data.source={self.source} требует data.root")
        return self


class OptimConfig(BaseModel):
    """Оптимизация: AdamW + warmup→cosine (стандарт 2026 для finetune CNN)."""

    epochs: int = Field(default=50, ge=1)
    lr: float = Field(default=3e-4, gt=0)
    weight_decay: float = Field(default=1e-4, ge=0)
    warmup_epochs: int = Field(default=3, ge=0)
    scheduler: SchedulerType = "cosine"
    min_lr_ratio: float = Field(default=0.01, ge=0.0, le=1.0)  # cosine: lr_min = lr * ratio
    label_smoothing: float = Field(default=0.1, ge=0.0, lt=1.0)
    class_weights: Literal["auto", "none"] | list[float] = "auto"
    mixup_alpha: float = Field(default=0.0, ge=0.0)  # 0 → выкл
    angle_loss_weight: float = Field(default=1.0, ge=0.0)


class TrainSection(BaseModel):
    """Режим исполнения и критерий выбора лучшей эпохи."""

    device: str = "auto"  # auto|cpu|cuda|cuda:N
    amp: AmpMode = "auto"  # auto: bf16 на CUDA c поддержкой, иначе fp16; на CPU — off
    channels_last: bool = True
    compile: bool = False  # torch.compile (opt-in: первый шаг медленный)
    ema_decay: float = Field(default=0.0, ge=0.0, lt=1.0)  # 0 → выкл; типично 0.999
    early_stopping_patience: int = Field(default=15, ge=0)  # 0 → выкл
    monitor: MonitorMetric = "balanced_accuracy"
    runs_dir: str = "data/ml_train/runs"
    run_name: str | None = None  # None → <arch>_<timestamp>


class ExportConfig(BaseModel):
    """Авто-экспорт лучшей модели в ONNX + sidecar для ml_inference."""

    auto: bool = False
    models_dir: str = "data/models"
    opset: int = Field(default=17, ge=11)


class TrainConfig(BaseModel):
    """Корневой конфиг прогона обучения."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    optim: OptimConfig = Field(default_factory=OptimConfig)
    train: TrainSection = Field(default_factory=TrainSection)
    export: ExportConfig = Field(default_factory=ExportConfig)

    @model_validator(mode="after")
    def _check_cross(self) -> TrainConfig:
        if self.optim.mixup_alpha > 0 and self.model.angle_head:
            raise ValueError("mixup несовместим с angle_head: угловые метки не смешиваются")
        if self.train.monitor == "angle_mae_deg" and not self.model.angle_head:
            raise ValueError("monitor=angle_mae_deg требует model.angle_head=true")
        if self.train.monitor == "angle_mae_deg" and self.data.source == "folder":
            raise ValueError("monitor=angle_mae_deg недоступен для source=folder (нет меток угла)")
        if self.model.angle_head and self.data.source == "folder":
            # folder-датасет не несёт углов (angle_valid=False) → голова угла учится
            # на нулях, а sidecar объявит angle_head=True/symmetry={} → инференс
            # вернёт valid=True с мусорным углом → робот доворачивает наугад
            raise ValueError(
                "angle_head=True несовместим с source=folder: нет меток угла. "
                "Используйте source=synthetic (dataset_gen) или exported (с углами)."
            )
        return self

    @property
    def monitor_mode(self) -> Literal["min", "max"]:
        """Направление оптимизации монитор-метрики."""
        return "min" if self.train.monitor in MINIMIZE_METRICS else "max"

    # ------------------------------------------------------------------ #
    # Dict at Boundary
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainConfig:
        """Pre: data — словарь секций. Post: валидный TrainConfig (иначе ValidationError)."""
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TrainConfig:
        """Загрузить конфиг из YAML-файла."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"конфиг не является YAML-словарём: {path}")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (tuple → list делает model_dump(mode='json'))."""
        return self.model_dump(mode="json")

    def to_yaml(self, path: str | Path) -> Path:
        """Сохранить конфиг в YAML (для воспроизводимости прогона)."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return out
