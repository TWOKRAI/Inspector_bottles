"""Типы данных портов Pipeline — enum-based API для Task 9.1.

Параллельный API поверх строкового port_types.py. Старый API (are_ports_compatible)
не затронут — он расширяется отдельно в Task 9.2/9.7.
"""

from __future__ import annotations

from enum import Enum


class DataType(str, Enum):
    """Тип данных, передаваемых между нодами DAG-пайплайна.

    Наследуется от str, чтобы round-trip сериализация в YAML/JSON работала
    без кастомных сериализаторов: json.dumps(DataType.BGR_IMAGE) → '"bgr_image"'.
    """

    BGR_IMAGE = "bgr_image"       # numpy ndarray uint8 HxWx3 (BGR-порядок каналов)
    GRAYSCALE = "grayscale"       # numpy ndarray uint8 HxW (одноканальный)
    BINARY_MASK = "binary_mask"   # numpy ndarray uint8 HxW (значения 0 или 255)
    BBOX_LIST = "bbox_list"       # list[dict] — детекции с bbox-координатами
    KEYPOINTS = "keypoints"       # list[dict] — ключевые точки
    CONTOURS = "contours"         # list[numpy.ndarray] — контуры (findContours)
    SCALAR = "scalar"             # int или float — одиночное числовое значение
    STRING = "string"             # str — текстовое значение
    DICT = "dict"                 # dict — произвольный словарь
    TENSOR = "tensor"             # torch.Tensor или numpy ndarray (общий случай)
    ANY = "any"                   # универсальный — совместим с любым типом

    @property
    def format_label(self) -> str:
        """Человекочитаемое описание типа для отображения в UI."""
        return _FORMAT_LABELS.get(self, self.name)


# ---------------------------------------------------------------------------
# Метки для UI
# ---------------------------------------------------------------------------

_FORMAT_LABELS: dict[DataType, str] = {
    DataType.BGR_IMAGE: "BGR uint8 HxWx3",
    DataType.GRAYSCALE: "Gray uint8 HxW",
    DataType.BINARY_MASK: "Binary uint8 HxW (0/255)",
    DataType.BBOX_LIST: "BBox list[dict]",
    DataType.KEYPOINTS: "Keypoints list[dict]",
    DataType.CONTOURS: "Contours list[ndarray]",
    DataType.SCALAR: "Scalar (int/float)",
    DataType.STRING: "String",
    DataType.DICT: "Dict",
    DataType.TENSOR: "Tensor (torch/numpy)",
    DataType.ANY: "Any",
}


# ---------------------------------------------------------------------------
# Пары типов, совместимые по формату (помимо строгого равенства)
# ---------------------------------------------------------------------------
# Читать как: «выход типа X можно подключить к входу типа Y и наоборот».
# GRAYSCALE и BINARY_MASK оба являются uint8 HxW → взаимозаменяемы.

_COMPATIBLE_PAIRS: set[frozenset[DataType]] = {
    frozenset({DataType.GRAYSCALE, DataType.BINARY_MASK}),
}


def is_compatible(output_type: DataType, input_type: DataType) -> bool:
    """Проверяет, можно ли подключить выход output_type к входу input_type.

    Правила проверки (в порядке приоритета):
    1. Любая из сторон ANY → True (универсальный тип совместим со всем).
    2. output_type == input_type → True (строгое совпадение).
    3. frozenset пары входит в _COMPATIBLE_PAIRS → True (явная совместимость).
    4. Иначе → False.

    Args:
        output_type: тип данных выходного порта источника.
        input_type: тип данных входного порта получателя.

    Returns:
        True если соединение допустимо, False иначе.
    """
    # Правило 1: ANY совместим с чем угодно в обе стороны
    if output_type == DataType.ANY or input_type == DataType.ANY:
        return True

    # Правило 2: строгое совпадение типов
    if output_type == input_type:
        return True

    # Правило 3: явно объявленные совместимые пары
    return frozenset({output_type, input_type}) in _COMPATIBLE_PAIRS


__all__ = [
    "DataType",
    "is_compatible",
    "_COMPATIBLE_PAIRS",
]
