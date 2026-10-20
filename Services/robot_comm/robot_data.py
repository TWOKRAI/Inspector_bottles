"""Форматы данных робота: параметры, точки, системы координат, программы (T5.3b).

Purpose:
    Читать и писать документы ``RobotDataStore`` в формате робота v2 с проверкой содержимого. Хранилище
    (``store.py``) схем не знает — этот модуль знает: ``params.yaml``, ``points.yaml``, ``frames.yaml``,
    ``programs/<имя>.yaml``. Всё, что не прошло проверку, — ``RobotDataInvalid(rev)``; ``rev`` — ревизия байтов
    файла, по ней вызывающий может сознательно перезаписать. Текст ошибки постоянный, без входных значений.
    Потоков, процессов, команд хаба и GUI здесь нет; конкурентность — замки хранилища (один замок на документ).

Public API:
    ``ParamsDoc(values, epoch, rev)``, ``param_bounds``, ``load_params``, ``save_params``, ``make_param_source``
    (для ``param_source=`` драйвера v2), ``load_points``, ``save_points``, ``load_frames``, ``save_frames``,
    ``load_program``, ``save_program``, ``delete_program``.

Stability: lite (новый модуль без Protocol-интерфейса; контракт держат ``Pre:``/``Post:`` функций и тесты).

Форматы (все верхнего уровня — словарь с ``version: 1``; лишние ключи — отказ):
    * ``params.yaml``  — ``{"version": 1, "epoch": <int 1..65535>, "values": {<имя параметра>: <сырое int>}}``;
      имя ∈ ``PARAM_ID`` без ``P_CONFIG_EPOCH`` (метка ПК лежит в ``epoch``), сырое — в ``min..max`` таблицы.
    * ``points.yaml``  — ``{"version": 1, "points": [Point.to_dict(), ...]}``, имена точек уникальны.
    * ``frames.yaml``  — ``{"version": 1, "frames": [FrameDef.to_dict(), ...]}``, имена СК уникальны.
    * программа        — ``Program.to_dict()``; имя в теле равно имени файла.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.errors import RobotDataInvalid, RobotWatchdogDisabled
from Services.robot_comm.programs.program import FrameDef, Point, Program
from Services.robot_comm.store import RobotDataStore

__all__ = [
    "ParamsDoc",
    "delete_program",
    "load_frames",
    "load_params",
    "load_points",
    "load_program",
    "make_param_source",
    "param_bounds",
    "save_frames",
    "save_params",
    "save_points",
    "save_program",
]

_VERSION = 1
_EPOCH_MIN = 1
_EPOCH_MAX = 65535
#: Имена параметров, значения которых лежат в ``values``; метка ПК ``P_CONFIG_EPOCH`` хранится отдельным полем.
_VALUE_NAMES = tuple(name for name in PARAM_ID if name != "P_CONFIG_EPOCH")


@dataclass(frozen=True)
class ParamsDoc:
    """Параметры робота: ``values`` — сырые int всех имён ``_VALUE_NAMES``, ``epoch`` — метка ПК,
    ``rev`` — ревизия файла (None, когда файла нет)."""

    values: dict[str, int]
    epoch: int
    rev: str | None


# ---------------------------------------------------------------------- #
# проверки
# ---------------------------------------------------------------------- #


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_header(body: Mapping[Any, Any], keys: set[str], rev: str | None) -> None:
    """``version == 1`` (целое, не bool) и ровно ключи ``keys`` + ``version``; иначе ``RobotDataInvalid(rev)``."""
    version = body.get("version")
    if type(version) is not int or version != _VERSION or set(body) != keys | {"version"}:
        raise RobotDataInvalid(rev)


def _check_epoch(epoch: object, rev: str | None) -> int:
    if not _is_int(epoch) or not _EPOCH_MIN <= epoch <= _EPOCH_MAX:  # type: ignore[operator]
        raise RobotDataInvalid(rev)
    return epoch  # type: ignore[return-value]


#: Параметр сторожа: 0 в таблице протокола значит «выключен», в продукте это отказ (DESIGN 8, T5.3c).
_WDG_NAME = "P_WDG_TIMEOUT_MS"
_WDG_MIN = 1


def param_bounds(name: str) -> tuple[int, int]:
    """Границы сырого значения параметра ``name``: ``(min, max)`` таблицы протокола; для сторожа минимум 1.

    Pre: ``name`` — имя из ``_VALUE_NAMES`` (``P_CONFIG_EPOCH`` не входит: метка ПК лежит в ``epoch``).
    Post: чистая функция, диск не трогает; её границы совпадают с проверкой ``load_params`` / ``save_params``.
    Raises: ``RobotDataInvalid(None)`` — неизвестное имя или ``P_CONFIG_EPOCH`` (именно ``RobotDataInvalid``).
    """
    if not isinstance(name, str) or name not in _VALUE_NAMES:
        raise RobotDataInvalid(None)
    meta = PARAMS[PARAM_ID[name]]
    low = _WDG_MIN if name == _WDG_NAME else meta["min"]
    return int(low), int(meta["max"])


def _check_values(values: object, rev: str | None) -> dict[str, int]:
    """Имена ∈ ``_VALUE_NAMES``, сырые — целые в ``param_bounds``; иначе ``RobotDataInvalid(rev)``.

    ``P_WDG_TIMEOUT_MS = 0`` — ``RobotWatchdogDisabled(rev)`` (подкласс); правило стоит до проверки границ.
    """
    if not isinstance(values, Mapping):
        raise RobotDataInvalid(rev)
    checked: dict[str, int] = {}
    for name, raw in values.items():
        if name not in _VALUE_NAMES or not _is_int(raw):
            raise RobotDataInvalid(rev)
        if name == _WDG_NAME and raw == 0:
            raise RobotWatchdogDisabled(rev)
        low, high = param_bounds(name)
        if not low <= raw <= high:
            raise RobotDataInvalid(rev)
        checked[name] = raw
    return checked


# ---------------------------------------------------------------------- #
# параметры
# ---------------------------------------------------------------------- #


def load_params(
    store: RobotDataStore,
    device_id: str,
    *,
    overrides: Mapping[str, int] | None = None,
    epoch_default: int = 1,
) -> ParamsDoc:
    """Прочитать параметры робота.

    Pre: ``device_id`` — ключ хранилища; ``overrides`` — сырые значения поверх умолчаний
    (``entry.params["robot_params"]``), ``epoch_default`` — метка, когда файла нет.
    Post: файла нет -> умолчания ``PARAMS[id]["default"]`` всех имён без ``P_CONFIG_EPOCH``, поверх них ``overrides``,
    метка ``epoch_default``, ``rev=None``. Файл есть -> умолчания, поверх них ``values`` файла, метка файла,
    ``rev`` файла; ``overrides`` при файле проверяются, но НЕ применяются (источник истины — файл). Диск не меняется.
    Raises: ``InvalidStoreKey``; ``StoreDocumentInvalid(rev)`` — файл не YAML-словарь; ``RobotDataInvalid(rev)`` —
    ``version != 1``, лишние или недостающие ключи, неизвестное имя, сырое вне ``min..max``, метка вне ``1..65535``;
    ``RobotDataInvalid(None)`` — неизвестное имя или недопустимое значение в ``overrides`` (файл есть или нет),
    либо недопустимая ``epoch_default`` (файла нет).
    """
    stored = store.read(device_id, "params")
    values = {name: int(PARAMS[PARAM_ID[name]]["default"]) for name in _VALUE_NAMES}
    checked_overrides = _check_values(overrides or {}, None)  # ошибка вызывающего, а не файла: проверка всегда
    if stored.body is None:
        values.update(checked_overrides)
        return ParamsDoc(values, _check_epoch(epoch_default, None), None)
    rev = stored.rev
    _check_header(stored.body, {"epoch", "values"}, rev)
    epoch = _check_epoch(stored.body["epoch"], rev)
    values.update(_check_values(stored.body["values"], rev))
    return ParamsDoc(values, epoch, rev)


def save_params(
    store: RobotDataStore,
    device_id: str,
    values: Mapping[str, int],
    epoch: int,
    *,
    base_rev: str | None,
) -> str:
    """Записать параметры робота целиком (полная карта ``values``, метка ``epoch``).

    Pre: ``values`` — полная карта, все имена без ``P_CONFIG_EPOCH`` (``_VALUE_NAMES``); ``values`` и ``epoch``
    проходят те же проверки, что при чтении; ``base_rev`` — как у ``RobotDataStore.write``.
    Post: успех -> новая ревизия файла. Отказ -> диск не тронут.
    Raises: ``RobotDataInvalid(None)`` — недопустимое, недостающее или лишнее имя, недопустимое значение или метка
    (до обращения к диску);
    ``InvalidStoreKey``; ``RevisionConflict(current_rev)``.
    """
    checked = _check_values(values, None)
    if set(checked) != set(_VALUE_NAMES):  # неполная карта затёрла бы остальные параметры умолчаниями при чтении
        raise RobotDataInvalid(None)
    body = {"version": _VERSION, "epoch": _check_epoch(epoch, None), "values": checked}
    return store.write(device_id, "params", body, base_rev=base_rev)


def make_param_source(
    store: RobotDataStore,
    device_id: str,
    *,
    overrides: Mapping[str, int] | None = None,
    epoch_default: int = 1,
) -> Callable[[], tuple[dict[str, int], int]]:
    """Источник параметров для ``RobotDriverV2(param_source=...)``: ``() -> (сырые значения, метка)``.

    Post: каждый вызов источника читает файл заново (``load_params``); ``overrides`` запоминаются копией.
    Источник бросает те же ошибки, что ``load_params``.
    """
    fixed = None if overrides is None else dict(overrides)

    def source() -> tuple[dict[str, int], int]:
        doc = load_params(store, device_id, overrides=fixed, epoch_default=epoch_default)
        return dict(doc.values), doc.epoch

    return source


# ---------------------------------------------------------------------- #
# точки и системы координат
# ---------------------------------------------------------------------- #


def _load_collection[T: (Point, FrameDef)](
    store: RobotDataStore, device_id: str, doc: str, key: str, model: type[T]
) -> tuple[dict[str, T], str | None]:
    stored = store.read(device_id, doc)
    if stored.body is None:
        return {}, None
    rev = stored.rev
    _check_header(stored.body, {key}, rev)
    items = stored.body[key]
    if not isinstance(items, list):
        raise RobotDataInvalid(rev)
    loaded: dict[str, T] = {}
    for item in items:
        try:
            obj = model.from_dict(item)
        except (ValidationError, ValueError, TypeError) as exc:  # данные из файла: pydantic и геометрия -> доменная
            raise RobotDataInvalid(rev) from exc
        if obj.name in loaded:
            raise RobotDataInvalid(rev)
        loaded[obj.name] = obj
    return loaded, rev


def _save_collection[T: (Point, FrameDef)](
    store: RobotDataStore, device_id: str, doc: str, key: str, items: Mapping[str, T], base_rev: str | None
) -> str:
    for name, obj in items.items():
        if name != obj.name:
            raise RobotDataInvalid(None)
    body = {"version": _VERSION, key: [obj.to_dict() for obj in items.values()]}
    return store.write(device_id, doc, body, base_rev=base_rev)


def load_points(store: RobotDataStore, device_id: str) -> tuple[dict[str, Point], str | None]:
    """Прочитать точки устройства: ``({имя: Point}, rev)``; файла нет -> ``({}, None)``.

    Raises: ``InvalidStoreKey``; ``StoreDocumentInvalid(rev)``; ``RobotDataInvalid(rev)`` — ``version != 1``, лишние
    ключи, точка не прошла проверку ``Point`` (в том числе ``hand`` не 0/1), повтор имени.
    """
    return _load_collection(store, device_id, "points", "points", Point)


def save_points(store: RobotDataStore, device_id: str, points: Mapping[str, Point], *, base_rev: str | None) -> str:
    """Записать все точки устройства (ключ карты равен ``Point.name``); возвращает новую ревизию.

    Raises: ``RobotDataInvalid(None)`` — ключ карты не равен имени точки; ``InvalidStoreKey``; ``RevisionConflict``.
    """
    return _save_collection(store, device_id, "points", "points", points, base_rev)


def load_frames(store: RobotDataStore, device_id: str) -> tuple[dict[str, FrameDef], str | None]:
    """Прочитать системы координат устройства: ``({имя: FrameDef}, rev)``; файла нет -> ``({}, None)``.

    Raises: как у ``load_points`` (СК проверяет ``FrameDef``, в том числе вырожденность).
    """
    return _load_collection(store, device_id, "frames", "frames", FrameDef)


def save_frames(store: RobotDataStore, device_id: str, frames: Mapping[str, FrameDef], *, base_rev: str | None) -> str:
    """Записать все системы координат устройства (ключ карты равен ``FrameDef.name``); возвращает новую ревизию.

    Raises: как у ``save_points``.
    """
    return _save_collection(store, device_id, "frames", "frames", frames, base_rev)


# ---------------------------------------------------------------------- #
# программы
# ---------------------------------------------------------------------- #


def load_program(store: RobotDataStore, device_id: str, name: str) -> tuple[Program | None, str | None]:
    """Прочитать программу ``name``: ``(Program, rev)``; файла нет -> ``(None, None)``.

    Raises: ``InvalidStoreKey``; ``StoreDocumentInvalid(rev)``; ``RobotDataInvalid(rev)`` — тело не прошло проверку
    ``Program`` или имя в теле не равно ``name``.
    """
    stored = store.read_program(device_id, name)
    if stored.body is None:
        return None, None
    rev = stored.rev
    try:
        program = Program.from_dict(stored.body)
    except (ValidationError, ValueError, TypeError) as exc:  # данные из файла: см. _load_collection
        raise RobotDataInvalid(rev) from exc
    if program.name != name:
        raise RobotDataInvalid(rev)
    return program, rev


def save_program(store: RobotDataStore, device_id: str, program: Program, *, base_rev: str | None) -> str:
    """Записать программу в файл ``programs/<program.name>.yaml``; возвращает новую ревизию.

    Raises: ``InvalidStoreKey`` — имя не годится в имя файла; ``RevisionConflict(current_rev)``.
    """
    return store.write_program(device_id, program.name, program.to_dict(), base_rev=base_rev)


def delete_program(store: RobotDataStore, device_id: str, name: str, *, base_rev: str | None) -> None:
    """Удалить программу: проход в ``RobotDataStore.delete_program`` (ревизия проверяется под замком документа)."""
    store.delete_program(device_id, name, base_rev=base_rev)
