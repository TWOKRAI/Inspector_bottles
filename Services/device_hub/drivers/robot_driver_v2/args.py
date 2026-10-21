"""``robot_driver_v2.args`` (T5.3f f2).

Purpose:
    Проверка аргументов операций драйвера робота Delta v2 (R8): разбор чисел и имён, отказы хранилища.

Stability: lite
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from Services.device_hub.drivers.robot_driver_v2.texts import _WIRE_MAX, _WIRE_SCALE
from Services.device_hub.robot_data_ops import TEXT_STORE_ERROR
from Services.robot_comm.errors import InvalidStoreKey, RevisionConflict, RobotDataInvalid, StoreDocumentInvalid

__all__ = [
    "_BadArgs",
    "_STORE_ERRORS",
    "_StoreIOError",
    "_base_rev_arg",
    "_bool_arg",
    "_check_wire",
    "_coord",
    "_int_in",
    "_is_int",
    "_name_arg",
    "_number_arg",
    "_store_refusal",
    "_strict_coord",
    "_whole",
]


class _BadArgs(Exception):
    """Аргумент операции не прошёл проверку R8. Текст ответа — постоянный, задаёт вызывающий."""


def _coord(args: Mapping[str, Any], key: str, default: float | None = None) -> float:
    """Координата из аргументов: конечное число, ``|v| * WIRE_SCALE <= W_MAX``; нет ключа и нет умолчания — ошибка."""
    raw = args.get(key)
    if raw is None:
        if default is None:
            raise _BadArgs(key)
        return default
    if isinstance(raw, bool):
        raise _BadArgs(key)
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):  # 10**400 -> OverflowError
        raise _BadArgs(key) from None
    _check_wire(value, key)
    return value


def _strict_coord(args: Mapping[str, Any], key: str, default: float | None = None) -> float:
    """``_coord`` без числа-строкой (``"10"`` — ``_BadArgs``): то же правило, что у ``param_set`` и ``robot_params``."""
    if isinstance(args.get(key), str):
        raise _BadArgs(key)
    return _coord(args, key, default)


def _check_wire(value: float, what: str) -> None:
    if not math.isfinite(value) or abs(value) * _WIRE_SCALE > _WIRE_MAX:
        raise _BadArgs(what)


def _whole(raw: Any, key: str) -> int:
    """Целое без дробной части (``e_capture``); bool, строка не-числа, nan, 1.5 — ошибка."""
    if isinstance(raw, bool):
        raise _BadArgs(key)
    if isinstance(raw, int):
        return raw
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _BadArgs(key) from None
    if not math.isfinite(value) or not value.is_integer():
        raise _BadArgs(key)
    return int(value)


def _int_in(args: Mapping[str, Any], key: str, low: int, high: int) -> int:
    """Целое ``low..high`` (bool не годится, строка и дробное — тоже); иначе ``_BadArgs``."""
    raw = args.get(key)
    if type(raw) is not int or not low <= raw <= high:
        raise _BadArgs(key)
    return raw


def _bool_arg(args: Mapping[str, Any], key: str) -> bool:
    raw = args.get(key)
    if type(raw) is not bool:
        raise _BadArgs(key)
    return raw


def _name_arg(args: Mapping[str, Any], key: str) -> str:
    raw = args.get(key)
    if type(raw) is not str or not raw:
        raise _BadArgs(key)
    return raw


def _base_rev_arg(args: Mapping[str, Any]) -> str | None:
    """Ключ ``base_rev`` обязателен (О6): нет ключа или не ``str | None`` — ``_BadArgs``."""
    if "base_rev" not in args:
        raise _BadArgs("base_rev")
    raw = args["base_rev"]
    if raw is not None and type(raw) is not str:
        raise _BadArgs("base_rev")
    return raw


def _number_arg(args: Mapping[str, Any], key: str) -> float:
    """Конечное число (bool не число, как ``_coord``); границы — у вызывающего."""
    raw = args.get(key)
    if type(raw) not in (int, float):
        raise _BadArgs(key)
    try:
        finite = math.isfinite(raw)
    except OverflowError:  # int > 1.8e308: в float не переводится
        finite = False
    if not finite:
        raise _BadArgs(key)
    return raw


class _StoreIOError(Exception):
    """``OSError`` хранилища (диск): полный текст — в логе, в ответ уходит ``TEXT_STORE_ERROR``."""


# Ошибки хранилища данных робота: операции драйвера отвечают их постоянным текстом, как ``DeviceManager.robot_data``
_STORE_ERRORS = (RevisionConflict, InvalidStoreKey, RobotDataInvalid, StoreDocumentInvalid, _StoreIOError)


def _store_refusal(exc: Exception) -> dict:
    """Ответ на ошибку хранилища: постоянный текст; конфликт ревизии несёт ``current_rev`` (как ``robot_data``)."""
    if isinstance(exc, RevisionConflict):
        return {"status": "error", "message": str(exc), "current_rev": exc.current_rev}
    if isinstance(exc, _StoreIOError):
        return {"status": "error", "message": TEXT_STORE_ERROR}
    return {"status": "error", "message": str(exc)}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
