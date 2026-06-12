"""Ядро генератора: конфиг, каталог, геометрия, аугментации, симметрия, движок."""

from Services.dataset_gen.core.catalog import SpriteCatalog, imread_unicode, imwrite_unicode
from Services.dataset_gen.core.config import GeneratorConfig, SymmetryType
from Services.dataset_gen.core.engine import DatasetEngine
from Services.dataset_gen.core.labels import SampleLabel
from Services.dataset_gen.core.symmetry import detect_symmetry, encode_angle, rotation_difference

__all__ = [
    "DatasetEngine",
    "GeneratorConfig",
    "SampleLabel",
    "SpriteCatalog",
    "SymmetryType",
    "detect_symmetry",
    "encode_angle",
    "rotation_difference",
    "imread_unicode",
    "imwrite_unicode",
]
