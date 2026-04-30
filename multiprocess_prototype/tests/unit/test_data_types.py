"""Unit-тесты для DataType enum и is_compatible (Task 9.1).

Покрывает: перечисление типов, правила совместимости,
round-trip сериализацию через str-enum и JSON.
"""

from __future__ import annotations

import json

import pytest

from multiprocess_prototype.registers.pipeline.types import (
    DataType,
    _COMPATIBLE_PAIRS,
    is_compatible,
)


# ===========================================================================
# Перечисление типов
# ===========================================================================


def test_data_type_count():
    """Ровно 11 типов перечислено в DataType."""
    assert len(list(DataType)) == 11


# ===========================================================================
# Совместимость с ANY
# ===========================================================================


def test_any_compatible_with_bgr_image():
    """ANY (выход) совместим с BGR_IMAGE (вход)."""
    assert is_compatible(DataType.ANY, DataType.BGR_IMAGE) is True


def test_bgr_image_compatible_with_any():
    """BGR_IMAGE (выход) совместим с ANY (вход)."""
    assert is_compatible(DataType.BGR_IMAGE, DataType.ANY) is True


def test_any_compatible_with_any():
    """ANY совместим с ANY."""
    assert is_compatible(DataType.ANY, DataType.ANY) is True


@pytest.mark.parametrize("dtype", [dt for dt in DataType if dt != DataType.ANY])
def test_any_compatible_with_all_types(dtype: DataType):
    """ANY совместим со всеми типами в обе стороны."""
    assert is_compatible(DataType.ANY, dtype) is True
    assert is_compatible(dtype, DataType.ANY) is True


# ===========================================================================
# Рефлексивность: тип совместим сам с собой
# ===========================================================================


@pytest.mark.parametrize("dtype", list(DataType))
def test_reflexivity(dtype: DataType):
    """Каждый тип совместим сам с собой."""
    assert is_compatible(dtype, dtype) is True


# ===========================================================================
# Пары из _COMPATIBLE_PAIRS — взаимная совместимость
# ===========================================================================


def test_grayscale_and_binary_mask_compatible_forward():
    """GRAYSCALE (выход) → BINARY_MASK (вход): совместимо."""
    assert is_compatible(DataType.GRAYSCALE, DataType.BINARY_MASK) is True


def test_grayscale_and_binary_mask_compatible_backward():
    """BINARY_MASK (выход) → GRAYSCALE (вход): совместимо."""
    assert is_compatible(DataType.BINARY_MASK, DataType.GRAYSCALE) is True


# ===========================================================================
# Несовместимые пары
# ===========================================================================


def test_bbox_list_incompatible_with_bgr_image():
    """BBOX_LIST и BGR_IMAGE несовместимы."""
    assert is_compatible(DataType.BBOX_LIST, DataType.BGR_IMAGE) is False


def test_bgr_image_incompatible_with_bbox_list():
    """BGR_IMAGE и BBOX_LIST несовместимы (симметрично)."""
    assert is_compatible(DataType.BGR_IMAGE, DataType.BBOX_LIST) is False


@pytest.mark.parametrize(
    "out_type, in_type",
    [
        (DataType.BGR_IMAGE, DataType.SCALAR),
        (DataType.CONTOURS, DataType.TENSOR),
        (DataType.STRING, DataType.DICT),
        (DataType.KEYPOINTS, DataType.GRAYSCALE),
    ],
)
def test_incompatible_pairs(out_type: DataType, in_type: DataType):
    """Заведомо несовместимые пары возвращают False."""
    assert is_compatible(out_type, in_type) is False


# ===========================================================================
# Round-trip сериализация — str-enum
# ===========================================================================


def test_str_value():
    """DataType.BGR_IMAGE.value == 'bgr_image'."""
    assert DataType.BGR_IMAGE.value == "bgr_image"


def test_str_lookup():
    """DataType('bgr_image') is DataType.BGR_IMAGE — поиск по строке."""
    assert DataType("bgr_image") is DataType.BGR_IMAGE


def test_str_enum_isinstance():
    """DataType является str — isinstance(DataType.SCALAR, str) is True."""
    assert isinstance(DataType.SCALAR, str) is True


@pytest.mark.parametrize("dtype", list(DataType))
def test_round_trip_all_types(dtype: DataType):
    """Все типы проходят round-trip через строковое значение."""
    assert DataType(dtype.value) is dtype


# ===========================================================================
# Round-trip сериализация — JSON
# ===========================================================================


def test_json_dumps_grayscale():
    """json.dumps(DataType.GRAYSCALE) возвращает '\"grayscale\"'."""
    assert json.dumps(DataType.GRAYSCALE) == '"grayscale"'


def test_json_loads_grayscale():
    """DataType(json.loads('\"grayscale\"')) is DataType.GRAYSCALE."""
    assert DataType(json.loads('"grayscale"')) is DataType.GRAYSCALE


@pytest.mark.parametrize("dtype", list(DataType))
def test_json_round_trip_all_types(dtype: DataType):
    """Все типы проходят полный JSON round-trip (dumps → loads → DataType)."""
    serialized = json.dumps(dtype)          # '"bgr_image"', '"any"', ...
    raw_value = json.loads(serialized)      # 'bgr_image', 'any', ...
    assert DataType(raw_value) is dtype


# ===========================================================================
# Метаданные: format_label
# ===========================================================================


def test_format_label_bgr_image():
    """format_label для BGR_IMAGE содержит осмысленное описание."""
    label = DataType.BGR_IMAGE.format_label
    assert "BGR" in label


def test_format_label_any():
    """format_label для ANY — 'Any'."""
    assert DataType.ANY.format_label == "Any"


@pytest.mark.parametrize("dtype", list(DataType))
def test_format_label_not_empty(dtype: DataType):
    """format_label определён и не пустой для всех типов."""
    label = dtype.format_label
    assert isinstance(label, str)
    assert len(label) > 0


# ===========================================================================
# Структура _COMPATIBLE_PAIRS
# ===========================================================================


def test_compatible_pairs_is_set_of_frozensets():
    """_COMPATIBLE_PAIRS — множество frozenset[DataType]."""
    assert isinstance(_COMPATIBLE_PAIRS, set)
    for pair in _COMPATIBLE_PAIRS:
        assert isinstance(pair, frozenset)
        # каждая пара содержит ровно 2 элемента
        assert len(pair) == 2


def test_grayscale_binary_mask_in_compatible_pairs():
    """GRAYSCALE↔BINARY_MASK присутствует в _COMPATIBLE_PAIRS."""
    pair = frozenset({DataType.GRAYSCALE, DataType.BINARY_MASK})
    assert pair in _COMPATIBLE_PAIRS
