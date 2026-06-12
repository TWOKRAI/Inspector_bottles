"""Конфигурация генератора синтетического датасета (Pydantic v2).

Принцип: ядро не знает предметной области. Всё специфичное для задачи —
каталог классов, диапазоны аугментаций, разрешение, симметрии — живёт здесь
и загружается из YAML-пресета. Смена задачи (буквы → цифры → детали) = смена
пресета, код движка не трогается.

Dict-at-boundary: `from_dict`/`to_dict`; `from_yaml` резолвит относительные
пути от каталога YAML-файла (пресет переносим вместе с данными).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

SymmetryType = Literal["none", "180", "full"]

RangeF = tuple[float, float]
RangeI = tuple[int, int]


# ---------------------------------------------------------------------------
# Аугментации: у каждой — выключатель, у стохастических — вероятность применения
# ---------------------------------------------------------------------------


class RotationAug(BaseModel):
    """Поворот эталона. Угол — ground truth метки (CCW, градусы)."""

    enabled: bool = True
    range: RangeF = (0.0, 360.0)


class ShiftAug(BaseModel):
    """Сдвиг центра объекта от центра кадра, доля размера кадра по каждой оси."""

    enabled: bool = True
    frac: float = Field(default=0.1, ge=0.0, le=0.5)


class ScaleAug(BaseModel):
    """Лёгкий случайный масштаб объекта (множитель к базовому размеру)."""

    enabled: bool = True
    range: RangeF = (0.9, 1.1)


class BrightnessContrastAug(BaseModel):
    """Яркость (аддитивно, шкала 0–255) и контраст (множитель вокруг 127.5)."""

    enabled: bool = True
    prob: float = Field(default=1.0, ge=0.0, le=1.0)
    brightness: RangeF = (-30.0, 30.0)
    contrast: RangeF = (0.85, 1.15)


class GaussianBlurAug(BaseModel):
    """Гауссово размытие всего кадра (расфокус)."""

    enabled: bool = True
    prob: float = Field(default=0.5, ge=0.0, le=1.0)
    sigma: RangeF = (0.4, 1.8)


class MotionBlurAug(BaseModel):
    """Смаз движения: линейное ядро случайной длины и направления."""

    enabled: bool = False
    prob: float = Field(default=0.5, ge=0.0, le=1.0)
    length: RangeI = (3, 9)


class NoiseAug(BaseModel):
    """Гауссов шум сенсора (std в шкале 0–255)."""

    enabled: bool = True
    prob: float = Field(default=0.7, ge=0.0, le=1.0)
    std: RangeF = (2.0, 10.0)


class ColorTemperatureAug(BaseModel):
    """Цветовая температура: shift>0 — теплее (R↑ B↓), shift<0 — холоднее."""

    enabled: bool = True
    prob: float = Field(default=0.5, ge=0.0, le=1.0)
    shift: RangeF = (-0.08, 0.08)


class JpegAug(BaseModel):
    """JPEG-артефакты: пережатие кадра со случайным качеством."""

    enabled: bool = False
    prob: float = Field(default=0.3, ge=0.0, le=1.0)
    quality: RangeI = (50, 90)


class GlareAug(BaseModel):
    """Блик-пятно: радиальный градиент пересвета (глянцевые поверхности).

    Обычная яркость блик не воспроизводит — нужен локальный пересвет.
    intensity — добавка яркости в центре пятна (0–255),
    radius_frac — радиус пятна как доля минимальной стороны кадра.
    """

    enabled: bool = False
    prob: float = Field(default=0.5, ge=0.0, le=1.0)
    intensity: RangeF = (40.0, 120.0)
    radius_frac: RangeF = (0.15, 0.45)


class AugmentConfig(BaseModel):
    """Полный набор аугментаций. Геометрия — до/при композиции, фотометрия —
    единым проходом на весь кадр ПОСЛЕ композиции (см. engine.generate_sample)."""

    rotation: RotationAug = Field(default_factory=RotationAug)
    shift: ShiftAug = Field(default_factory=ShiftAug)
    scale: ScaleAug = Field(default_factory=ScaleAug)
    brightness_contrast: BrightnessContrastAug = Field(default_factory=BrightnessContrastAug)
    gaussian_blur: GaussianBlurAug = Field(default_factory=GaussianBlurAug)
    motion_blur: MotionBlurAug = Field(default_factory=MotionBlurAug)
    noise: NoiseAug = Field(default_factory=NoiseAug)
    color_temperature: ColorTemperatureAug = Field(default_factory=ColorTemperatureAug)
    jpeg: JpegAug = Field(default_factory=JpegAug)
    glare: GlareAug = Field(default_factory=GlareAug)


# ---------------------------------------------------------------------------
# Каталог, размещение, симметрия, выход
# ---------------------------------------------------------------------------


class CatalogConfig(BaseModel):
    """Источники данных.

    classes_dir — каталог с подкаталогом на класс (имя подкаталога = имя класса),
    внутри один или несколько RGBA-эталонов (PNG/WebP/TIFF, объект на прозрачном фоне).
    backgrounds_dir — каталог фоновых RGB-фото; None → процедурные фоны
    (плавный градиент + шум) для быстрого старта и тестов.
    """

    classes_dir: Path
    backgrounds_dir: Path | None = None


class PlacementConfig(BaseModel):
    """Размещение объекта на фоне.

    object_size_frac — диапазон базового размера: длинная сторона объекта
    как доля минимальной стороны кадра (до scale-джиттера).
    keep_inside — прижимать центр так, чтобы объект не вылезал за кадр.
    """

    object_size_frac: RangeF = (0.5, 0.8)
    keep_inside: bool = True


class SymmetryConfig(BaseModel):
    """Определение симметрии классов.

    auto_detect — вычислять симметрию по эталонам (пиксельная разность поворотов).
    threshold — абсолютный порог нормированной разности [0..1].
    rel_threshold — относительный порог для 180°: разность на 180° должна быть
    меньше rel_threshold * (типичная разность на контрольных углах) — защита
    от «разбавления» метрики большой инвариантной областью (объект на диске).
    full_angles — углы серии для проверки полной симметрии (180° проверяется всегда).
    overrides — ручное переопределение по имени класса (пограничные случаи).
    """

    auto_detect: bool = True
    threshold: float = Field(default=0.05, gt=0.0, lt=1.0)
    rel_threshold: float = Field(default=0.3, gt=0.0, le=1.0)
    full_angles: tuple[float, ...] = (30.0, 45.0, 60.0, 90.0, 120.0, 135.0)
    overrides: dict[str, SymmetryType] = Field(default_factory=dict)


class OutputConfig(BaseModel):
    """Параметры выхода.

    size — (H, W) итогового кадра. frames_per_class — кадров на класс
    (дефолт для экспорта и длины torch-Dataset). supersample — композиция
    на холсте size*supersample с финальным ресайзом (сглаживание краёв;
    учтите: фотометрия применяется до ресайза, сильный шум/JPEG ослабнут).
    """

    size: tuple[int, int] = (128, 128)
    frames_per_class: int = Field(default=100, ge=1)
    supersample: float = Field(default=1.0, ge=1.0, le=4.0)


class GeneratorConfig(BaseModel):
    """Корневой конфиг движка. Создаётся из YAML-пресета или dict."""

    catalog: CatalogConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    placement: PlacementConfig = Field(default_factory=PlacementConfig)
    symmetry: SymmetryConfig = Field(default_factory=SymmetryConfig)
    augment: AugmentConfig = Field(default_factory=AugmentConfig)
    seed: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> GeneratorConfig:
        """Создать конфиг из dict; относительные пути резолвятся от base_dir.

        Pre:
          - data содержит секцию catalog с classes_dir
        Post:
          - catalog.classes_dir и backgrounds_dir абсолютны, если задан base_dir
        """
        cfg = cls.model_validate(data)
        if base_dir is not None:
            base = Path(base_dir)
            cat = cfg.catalog
            if not cat.classes_dir.is_absolute():
                cat.classes_dir = (base / cat.classes_dir).resolve()
            if cat.backgrounds_dir is not None and not cat.backgrounds_dir.is_absolute():
                cat.backgrounds_dir = (base / cat.backgrounds_dir).resolve()
        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> GeneratorConfig:
        """Загрузить пресет из YAML; относительные пути — от каталога файла."""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Пресет {p}: ожидался YAML-словарь, получено {type(data).__name__}")
        return cls.from_dict(data, base_dir=p.parent)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (Path → str)."""
        d = self.model_dump(mode="json")
        return d
