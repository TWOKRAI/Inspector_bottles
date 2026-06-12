"""dataset_gen — универсальный генератор синтетического датасета (cut-and-paste).

Задача: классификация объекта + регрессия угла поворота. Ядро не знает
предметной области — работает с абстракцией «класс = RGBA-эталоны на
прозрачном фоне»; вся специфика (классы, аугментации, разрешение) — в
YAML-пресете. В комплекте пресет под русские буквы на дисках:
    presets/ru_letters_disk.yaml (+ tools/make_ru_letter_sprites.py)

Архитектура (по образцу Services/ml_inference):
    core/            — конфиг, каталог, геометрия, аугментации, симметрия, движок
    export.py        — режим 1: датасет на диск (PNG + labels csv/json/parquet)
    torch_adapter.py — режим 2: on-the-fly torch Dataset (лениво, torch опционален)
    preview.py       — QC-сетка кадров с подписями
    interfaces.py    — Protocol SampleGenerator

Публичный API (eager — без torch):
    DatasetEngine, GeneratorConfig, SampleLabel, SampleGenerator,
    detect_symmetry, encode_angle, export_dataset, save_preview_grid, PRESETS_DIR

Лениво (требует torch):
    from Services.dataset_gen import SyntheticDataset
"""

from pathlib import Path

from Services.dataset_gen.core import (
    ClassMeta,
    DatasetEngine,
    GeneratorConfig,
    SampleLabel,
    SymmetryType,
    detect_symmetry,
    encode_angle,
)
from Services.dataset_gen.export import export_dataset, export_splits
from Services.dataset_gen.interfaces import SampleGenerator
from Services.dataset_gen.preview import save_preview_grid

PRESETS_DIR = Path(__file__).parent / "presets"

__all__ = [
    "ClassMeta",
    "DatasetEngine",
    "GeneratorConfig",
    "SampleLabel",
    "SampleGenerator",
    "SymmetryType",
    "SyntheticDataset",
    "detect_symmetry",
    "encode_angle",
    "export_dataset",
    "export_splits",
    "save_preview_grid",
    "PRESETS_DIR",
]


def __getattr__(name: str):
    """Ленивая загрузка torch-адаптера (torch — опциональная зависимость)."""
    if name == "SyntheticDataset":
        from Services.dataset_gen.torch_adapter import SyntheticDataset

        return SyntheticDataset
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
