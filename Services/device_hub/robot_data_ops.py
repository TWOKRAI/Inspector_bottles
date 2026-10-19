"""Офлайн-операции с данными робота v2 для ``DeviceManager.robot_data`` (T5.3c, часть c1).

Purpose:
    Таблица ``OPS``: ``op -> fn(store, device_id, args) -> dict`` — параметры, точки, системы координат и
    программы робота из ``RobotDataStore``; драйвер и связь с роботом не нужны. Каждая операция проверяет аргументы
    ДО работы с диском; запись требует ключ ``base_rev`` (О6; значение ``None`` — «файла ещё нет»).
    Ошибки домена — ``RobotOpError`` с постоянным текстом без входных значений; плохие аргументы — ``BadArgs``
    (ответ — ``TEXT_BAD_ARGS``). Ошибки хранилища и формата (``RevisionConflict``, ``InvalidStoreKey``,
    ``RobotDataInvalid``, ``StoreDocumentInvalid``) пробрасываются: их превращает в ответ ``DeviceManager.robot_data``.

Public API:
    ``OPS``, ``TEXT_BAD_ARGS``, ``BadArgs``, ``RobotOpError``.

Stability: lite (контракт держат тесты ``test_robot_v2_commands*``).

Потоков и состояния нет; конкурентность — замки ``RobotDataStore`` (один замок на документ).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from Services.robot_comm.core.params_v2 import to_eng
from Services.robot_comm.programs.program import FrameDef, Point, Program
from Services.robot_comm.robot_data import (
    delete_program,
    load_frames,
    load_params,
    load_points,
    load_program,
    save_frames,
    save_points,
    save_program,
)
from Services.robot_comm.store import RobotDataStore

__all__ = ["OPS", "TEXT_BAD_ARGS", "BadArgs", "RobotOpError"]

#: Один текст на оба слоя (хаб и драйвер, T5.3d): плохие аргументы команды данных робота. Входные значения не попадают.
TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_NO_POINT = "точка не найдена"
TEXT_FRAME_DEGENERATE = "точки СК вырождены"
TEXT_FRAME_IN_BASE = "точка СК должна быть в базе"


class BadArgs(Exception):
    """Аргумент команды отсутствует или имеет неверный тип; ответ — ``TEXT_BAD_ARGS``."""


class RobotOpError(Exception):
    """Отказ операции данных с постоянным текстом (``str(exc)`` уходит в ответ как есть)."""


type OpFn = Callable[[RobotDataStore, str, dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------- #
# проверка аргументов (до работы с диском)
# ---------------------------------------------------------------------- #


def _name(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if type(value) is not str:
        raise BadArgs
    return value


def _mapping(args: dict[str, Any], key: str) -> dict[str, Any]:
    value = args.get(key)
    if not isinstance(value, dict):
        raise BadArgs
    return value


def _base_rev(args: dict[str, Any]) -> str | None:
    """Ключ ``base_rev`` обязателен у записи (О6): нет ключа или не ``str | None`` — ``BadArgs``."""
    if "base_rev" not in args:
        raise BadArgs
    value = args["base_rev"]
    if value is not None and type(value) is not str:
        raise BadArgs
    return value


# ---------------------------------------------------------------------- #
# параметры
# ---------------------------------------------------------------------- #


def _param_get_all(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    doc = load_params(store, device_id)
    params = {name: {"raw": raw, "value": float(to_eng(name, raw))} for name, raw in doc.values.items()}
    return {"params": params, "epoch": doc.epoch, "rev": doc.rev}


# ---------------------------------------------------------------------- #
# точки
# ---------------------------------------------------------------------- #


def _point_list(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    points, rev = load_points(store, device_id)
    return {"points": [p.to_dict() for p in points.values()], "rev": rev}


def _point_save(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    raw = _mapping(args, "point")
    base_rev = _base_rev(args)
    point = Point.from_dict(raw)  # pydantic ValidationError -> TEXT_BAD_ARGS в DeviceManager.robot_data
    points, _rev = load_points(store, device_id)
    points[point.name] = point  # вставка или замена по имени
    return {"rev": save_points(store, device_id, points, base_rev=base_rev)}


def _point_delete(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    name = _name(args, "name")
    base_rev = _base_rev(args)
    points, _rev = load_points(store, device_id)
    if name not in points:
        raise RobotOpError(TEXT_NO_POINT)
    del points[name]
    return {"rev": save_points(store, device_id, points, base_rev=base_rev)}


# ---------------------------------------------------------------------- #
# системы координат
# ---------------------------------------------------------------------- #


def _frame_list(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    frames, rev = load_frames(store, device_id)
    return {"frames": [f.to_dict() for f in frames.values()], "rev": rev}


def _frame_teach(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    name = _name(args, "name")
    origin, on_x, in_plane = _name(args, "origin"), _name(args, "on_x"), _name(args, "in_plane")
    base_rev = _base_rev(args)
    points, _points_rev = load_points(store, device_id)
    picked: list[Point] = []
    for point_name in (origin, on_x, in_plane):
        if point_name not in points:
            raise RobotOpError(TEXT_NO_POINT)
        picked.append(points[point_name])
    if any(p.frame is not None for p in picked):
        raise RobotOpError(TEXT_FRAME_IN_BASE)
    try:
        frame = FrameDef(
            name=name,
            origin=(picked[0].x, picked[0].y, picked[0].z),
            on_x=(picked[1].x, picked[1].y, picked[1].z),
            in_plane=(picked[2].x, picked[2].y, picked[2].z),
        )
    except ValidationError as exc:  # имя - str, координаты - float из файла: остаётся вырожденная геометрия
        raise RobotOpError(TEXT_FRAME_DEGENERATE) from exc
    frames, _rev = load_frames(store, device_id)
    frames[frame.name] = frame  # вставка или замена по имени (О7)
    return {"rev": save_frames(store, device_id, frames, base_rev=base_rev)}


# ---------------------------------------------------------------------- #
# программы
# ---------------------------------------------------------------------- #


def _program_list(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"programs": store.list_programs(device_id)}


def _program_get(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    name = _name(args, "name")
    program, rev = load_program(store, device_id, name)
    return {"program": None if program is None else program.to_dict(), "rev": rev}


def _program_save(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    raw = _mapping(args, "program")
    base_rev = _base_rev(args)
    program = Program.from_dict(raw)  # pydantic ValidationError -> TEXT_BAD_ARGS в DeviceManager.robot_data
    return {"rev": save_program(store, device_id, program, base_rev=base_rev)}


def _program_delete(store: RobotDataStore, device_id: str, args: dict[str, Any]) -> dict[str, Any]:
    name = _name(args, "name")
    base_rev = _base_rev(args)
    delete_program(store, device_id, name, base_rev=base_rev)
    return {}


#: op -> fn(store, device_id, args) -> dict (без ``status``: его добавляет ``DeviceManager.robot_data``).
OPS: dict[str, OpFn] = {
    "param_get_all": _param_get_all,
    "point_list": _point_list,
    "point_save": _point_save,
    "point_delete": _point_delete,
    "frame_list": _frame_list,
    "frame_teach": _frame_teach,
    "program_list": _program_list,
    "program_get": _program_get,
    "program_save": _program_save,
    "program_delete": _program_delete,
}
