"""Константы типов данных портов и таблица совместимости для графового редактора."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Константы типов данных портов
# ---------------------------------------------------------------------------

PORT_TYPE_IMAGE = "image"  # numpy.ndarray BGR
PORT_TYPE_MASK = "mask"  # numpy.ndarray grayscale / binary
PORT_TYPE_DETECTIONS = "detections"  # list[dict]
PORT_TYPE_CONTOURS = "contours"  # list[numpy.ndarray]
PORT_TYPE_ANY = "any"  # любой тип (для универсальных операций)

# ---------------------------------------------------------------------------
# Таблица совместимости: output_type → множество допустимых input_type
# ---------------------------------------------------------------------------
# Читать как: «выход с типом X можно подключить к входу с типом Y»
# "any" на входе принимает любой выход; "any" на выходе совместим только с "any"

COMPATIBLE_TYPES: dict[str, set[str]] = {
    PORT_TYPE_IMAGE: {PORT_TYPE_IMAGE, PORT_TYPE_ANY},
    PORT_TYPE_MASK: {PORT_TYPE_MASK, PORT_TYPE_ANY},
    PORT_TYPE_DETECTIONS: {PORT_TYPE_DETECTIONS, PORT_TYPE_ANY},
    PORT_TYPE_CONTOURS: {PORT_TYPE_CONTOURS, PORT_TYPE_ANY},
    PORT_TYPE_ANY: {
        PORT_TYPE_IMAGE,
        PORT_TYPE_MASK,
        PORT_TYPE_DETECTIONS,
        PORT_TYPE_CONTOURS,
        PORT_TYPE_ANY,
    },
}


def are_ports_compatible(output_type: str, input_type: str) -> bool:
    """Проверяет, можно ли подключить выход с output_type к входу с input_type.

    Args:
        output_type: тип данных выходного порта.
        input_type: тип данных входного порта.

    Returns:
        True если соединение допустимо, False иначе.
    """
    # Неизвестный тип — считаем несовместимым
    compatible_inputs = COMPATIBLE_TYPES.get(output_type, set())
    return input_type in compatible_inputs


__all__ = [
    "PORT_TYPE_IMAGE",
    "PORT_TYPE_MASK",
    "PORT_TYPE_DETECTIONS",
    "PORT_TYPE_CONTOURS",
    "PORT_TYPE_ANY",
    "COMPATIBLE_TYPES",
    "are_ports_compatible",
]
