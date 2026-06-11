"""Загрузчик YAML-протоколов устройств → RegisterMap + RegisterMeta.

Один YAML-файл описывает протокол одного устройства: адреса регистров (для
транспорта) + метаданные label/unit/min/max/hint (для GUI и валидации).

Структура файла::

    name: gd20_bridge
    kind: vfd
    description: "INVT GD20 через RS-485-мост робота (mailbox, Lua)"
    word_order: little      # big | little (дефолт big)
    registers:
      cmd_run:  {type: reg, address: 0x1200, access: w, label: "Пуск"}
      cmd_freq: {type: reg, address: 0x1202, scale: 100, unit: "Гц", min: 0, max: 50}
      status:
        type: block
        address: 0x1210
        access: r
        fields:
          - {name: running, label: "Вращение"}
          - {name: out_freq_hz, scale: 100, unit: "Гц"}

Типы записей зеркалят DSL ``register_map.py``:
    ``reg``   → Reg(address, scale, signed)
    ``dw``    → RegDW(address, scale, signed)
    ``block`` → RegBlock(address, fields=(...)) или RegBlock(address, count=N)

Метаданные (label/unit/hint/access/min/max/default) хранятся в RegisterMeta
и НЕ попадают в RegisterMap — та служит только транспортному слою.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from Services.modbus.core.register_map import (
    Field,
    Reg,
    RegBlock,
    RegDW,
    RegisterMap,
)

# ─────────────────────────────── константы ─────────────────────────────────── #

_VALID_ACCESS: frozenset[str] = frozenset({"r", "w", "rw"})
_VALID_WORD_ORDER: frozenset[str] = frozenset({"big", "little"})
_VALID_TYPES: frozenset[str] = frozenset({"reg", "dw", "block"})


# ──────────────────────────── публичные типы ────────────────────────────────── #


@dataclass(frozen=True)
class RegisterMeta:
    """GUI-метаданные одного регистра или поля блока.

    Attributes:
        name:    Имя записи (ключ в карте или поля блока).
        kind:    Тип записи: ``reg`` | ``dw`` | ``block`` | ``field``.
        label:   Русское название для GUI.
        unit:    Единица измерения (``Гц``, ``А``, ``В`` …).
        hint:    Подсказка оператору.
        access:  Режим доступа: ``r`` | ``w`` | ``rw``.
        scale:   Масштаб хранения (аналогично register_map).
        signed:  Знаковое значение.
        min:     Минимально допустимое значение (для валидации записи).
        max:     Максимально допустимое значение.
        default: Значение по умолчанию.
        fields:  Вложенные метаданные полей блока (рекурсивно).
    """

    name: str
    kind: str  # "reg" | "dw" | "block" | "field"
    label: str = ""
    unit: str = ""
    hint: str = ""
    access: str = "r"
    scale: float = 1.0
    signed: bool = False
    min: float | None = None
    max: float | None = None
    default: float | None = None
    fields: tuple["RegisterMeta", ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (Dict-at-Boundary).

        Поле ``fields`` рекурсивно преобразуется в список dict.
        """
        d: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "unit": self.unit,
            "hint": self.hint,
            "access": self.access,
            "scale": self.scale,
            "signed": self.signed,
            "min": self.min,
            "max": self.max,
            "default": self.default,
        }
        if self.fields:
            d["fields"] = [f.to_dict() for f in self.fields]
        return d


@dataclass(frozen=True)
class DeviceProtocol:
    """Загруженный протокол устройства.

    Attributes:
        name:         Имя протокола (поле ``name`` в файле).
        kind:         Тип устройства (``robot`` | ``vfd`` | …).
        description:  Произвольное описание (из файла или пустая строка).
        register_map: Карта регистров для транспортного слоя.
        meta:         Метаданные регистров для GUI (ключ = имя записи).
    """

    name: str
    kind: str
    description: str
    register_map: RegisterMap
    meta: dict[str, RegisterMeta]


class ProtocolFileError(Exception):
    """Ошибка разбора YAML-протокола.

    Сообщение содержит путь файла и имя проблемной записи.
    """


# ──────────────────────────── внутренние хелперы ────────────────────────────── #


def _require_int_address(value: Any, name: str, path: Path) -> int:
    """Проверить, что address — неотрицательное целое; PyYAML уже парсит 0x… как int."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFileError(f"{path}: запись {name!r}: address должен быть целым числом, получено {value!r}")
    if value < 0:
        raise ProtocolFileError(f"{path}: запись {name!r}: address не может быть отрицательным ({value})")
    return value


def _require_positive_scale(value: Any, name: str, path: Path) -> float:
    """Проверить, что scale > 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ProtocolFileError(f"{path}: запись {name!r}: scale должен быть числом, получено {value!r}") from None
    if v <= 0:
        raise ProtocolFileError(f"{path}: запись {name!r}: scale должен быть > 0, получено {v}")
    return v


def _require_valid_access(value: Any, name: str, path: Path) -> str:
    """Проверить, что access ∈ {r, w, rw}."""
    if value not in _VALID_ACCESS:
        raise ProtocolFileError(f"{path}: запись {name!r}: access {value!r} не из {{r, w, rw}}")
    return str(value)


def _parse_fields(
    raw_fields: list[Any],
    block_name: str,
    block_access: str,
    path: Path,
) -> tuple[tuple[Field, ...], tuple[RegisterMeta, ...]]:
    """Разобрать список полей блока → (Fields для карты, RegisterMeta для GUI)."""
    map_fields: list[Field] = []
    meta_fields: list[RegisterMeta] = []

    for idx, item in enumerate(raw_fields):
        if not isinstance(item, dict):
            raise ProtocolFileError(
                f"{path}: блок {block_name!r}: поле #{idx} должно быть dict, получено {type(item).__name__}"
            )
        fname = item.get("name")
        if not isinstance(fname, str) or not fname.strip():
            raise ProtocolFileError(f"{path}: блок {block_name!r}: поле #{idx}: отсутствует или пустое 'name'")

        scale = _require_positive_scale(item.get("scale", 1.0), f"{block_name}.{fname}", path)
        signed = bool(item.get("signed", False))
        # access поля наследуется от блока (если не задан явно)
        f_access = item.get("access", block_access)
        _require_valid_access(f_access, f"{block_name}.{fname}", path)

        map_fields.append(Field(fname, scale=scale, signed=signed))
        meta_fields.append(
            RegisterMeta(
                name=fname,
                kind="field",
                label=str(item.get("label", "")),
                unit=str(item.get("unit", "")),
                hint=str(item.get("hint", "")),
                access=f_access,
                scale=scale,
                signed=signed,
                min=float(item["min"]) if item.get("min") is not None else None,
                max=float(item["max"]) if item.get("max") is not None else None,
                default=float(item["default"]) if item.get("default") is not None else None,
            )
        )

    return tuple(map_fields), tuple(meta_fields)


def _parse_entry(
    name: str,
    raw: Any,
    path: Path,
    default_word_order: str,
) -> tuple[Reg | RegDW | RegBlock, RegisterMeta]:
    """Разобрать одну запись реестра → (map-entry, RegisterMeta).

    Поддерживаемые типы: ``reg``, ``dw``, ``block``.
    """
    if not isinstance(raw, dict):
        raise ProtocolFileError(f"{path}: запись {name!r}: ожидается dict, получено {type(raw).__name__}")

    entry_type = raw.get("type")
    if entry_type not in _VALID_TYPES:
        raise ProtocolFileError(
            f"{path}: запись {name!r}: неизвестный type {entry_type!r}; допустимые: {sorted(_VALID_TYPES)}"
        )

    address = _require_int_address(raw.get("address"), name, path)
    scale = _require_positive_scale(raw.get("scale", 1.0), name, path)
    signed = bool(raw.get("signed", False))
    access = _require_valid_access(raw.get("access", "r"), name, path)

    label = str(raw.get("label", ""))
    unit = str(raw.get("unit", ""))
    hint = str(raw.get("hint", ""))
    min_val = float(raw["min"]) if raw.get("min") is not None else None
    max_val = float(raw["max"]) if raw.get("max") is not None else None
    default_val = float(raw["default"]) if raw.get("default") is not None else None

    if entry_type == "reg":
        map_entry: Reg | RegDW | RegBlock = Reg(address, scale=scale, signed=signed)
        meta = RegisterMeta(
            name=name,
            kind="reg",
            label=label,
            unit=unit,
            hint=hint,
            access=access,
            scale=scale,
            signed=signed,
            min=min_val,
            max=max_val,
            default=default_val,
        )

    elif entry_type == "dw":
        map_entry = RegDW(address, scale=scale, signed=signed)
        meta = RegisterMeta(
            name=name,
            kind="dw",
            label=label,
            unit=unit,
            hint=hint,
            access=access,
            scale=scale,
            signed=signed,
            min=min_val,
            max=max_val,
            default=default_val,
        )

    else:  # block
        raw_fields = raw.get("fields")
        count_raw = raw.get("count")

        if raw_fields:
            # Блок с именованными полями
            map_fields, meta_fields = _parse_fields(raw_fields, name, access, path)
            map_entry = RegBlock(address, fields=map_fields)
        elif count_raw is not None:
            # Блок без имён полей — только count
            count = int(count_raw)
            if count <= 0:
                raise ProtocolFileError(f"{path}: блок {name!r}: count должен быть > 0, получено {count}")
            map_entry = RegBlock(address, count=count)
            meta_fields = ()
        else:
            raise ProtocolFileError(f"{path}: блок {name!r}: требуется 'fields' или 'count'")

        meta = RegisterMeta(
            name=name,
            kind="block",
            label=label,
            unit=unit,
            hint=hint,
            access=access,
            scale=scale,
            signed=signed,
            min=min_val,
            max=max_val,
            default=default_val,
            fields=meta_fields,
        )

    return map_entry, meta


def _check_address_overlaps(
    entries: list[tuple[str, Reg | RegDW | RegBlock]],
    path: Path,
) -> None:
    """Проверить дубли и перекрытия адресов с учётом ширины записей.

    Ширина: Reg = 1 слово, RegDW = 2 слова, RegBlock = count слов.
    """
    # Собрать занятые диапазоны [start, end) → имя
    ranges: list[tuple[int, int, str]] = []

    for name, entry in entries:
        if isinstance(entry, Reg):
            width = 1
        elif isinstance(entry, RegDW):
            width = 2
        else:
            width = entry.count

        addr = entry.address
        ranges.append((addr, addr + width, name))

    # Проверить попарные перекрытия (O(n²), обычно n < 50 — приемлемо)
    for i, (start_a, end_a, name_a) in enumerate(ranges):
        for start_b, end_b, name_b in ranges[i + 1 :]:
            if start_a < end_b and start_b < end_a:
                raise ProtocolFileError(
                    f"{path}: перекрытие адресов между {name_a!r} "
                    f"[0x{start_a:04X}..0x{end_a - 1:04X}] и {name_b!r} "
                    f"[0x{start_b:04X}..0x{end_b - 1:04X}]"
                )


# ──────────────────────────── публичный API ─────────────────────────────────── #


def load_protocol(path: Path) -> DeviceProtocol:
    """Загрузить YAML-протокол устройства из файла.

    Args:
        path: Путь к ``.yaml``-файлу протокола.

    Returns:
        DeviceProtocol с заполненными register_map и meta.

    Raises:
        ProtocolFileError: При любой ошибке формата или валидации.
        FileNotFoundError: Если файл не найден.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ProtocolFileError(f"{path}: ошибка разбора YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ProtocolFileError(f"{path}: корень файла должен быть YAML-словарём")

    # ── Шапка ── #
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProtocolFileError(f"{path}: обязательное поле 'name' отсутствует или пустое")

    kind = data.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ProtocolFileError(f"{path}: обязательное поле 'kind' отсутствует или пустое")

    description = str(data.get("description", ""))

    word_order_raw = data.get("word_order", "big")
    if word_order_raw not in _VALID_WORD_ORDER:
        raise ProtocolFileError(f"{path}: word_order {word_order_raw!r} не из {{big, little}}")
    word_order: str = word_order_raw

    # ── Регистры ── #
    registers_raw = data.get("registers")
    if not isinstance(registers_raw, dict):
        raise ProtocolFileError(f"{path}: поле 'registers' должно быть YAML-словарём")

    # Проверить имена на пустоту / дубли (YAML не допускает дублей ключей по умолчанию,
    # но явно проверяем пустые имена)
    for reg_name in registers_raw:
        if not isinstance(reg_name, str) or not reg_name.strip():
            raise ProtocolFileError(f"{path}: пустое или невалидное имя записи: {reg_name!r}")

    # ── Разбор записей ── #
    map_entries: dict[str, Reg | RegDW | RegBlock] = {}
    meta_entries: dict[str, RegisterMeta] = {}

    for reg_name, reg_raw in registers_raw.items():
        map_entry, meta = _parse_entry(reg_name, reg_raw, path, word_order)
        map_entries[reg_name] = map_entry
        meta_entries[reg_name] = meta

    # ── Проверка перекрытий адресов ── #
    _check_address_overlaps(list(map_entries.items()), path)

    register_map = RegisterMap(map_entries, word_order=word_order)  # type: ignore[arg-type]

    return DeviceProtocol(
        name=name,
        kind=kind,
        description=description,
        register_map=register_map,
        meta=meta_entries,
    )


def find_protocols(kind: str | None = None) -> dict[str, Path]:
    """Найти все YAML-протоколы в Services/*/protocols/*.yaml.

    Сканирует директорию ``Services/`` от расположения этого модуля.
    Ключ словаря — stem (имя файла без расширения).

    Args:
        kind: Если задан — фильтрует по полю ``kind`` внутри файла.
              Битые или недоступные файлы пропускаются с предупреждением.

    Returns:
        Словарь ``{stem: Path}`` найденных протоколов.
    """
    # Services/ = parents[2] относительно этого файла:
    # Services/modbus/core/protocol_file.py
    #          ^[2] ^[1]  ^[0]
    services_root = Path(__file__).resolve().parents[2]
    result: dict[str, Path] = {}

    for yaml_path in sorted(services_root.glob("*/protocols/*.yaml")):
        stem = yaml_path.stem
        if kind is not None:
            # Читаем только шапку для проверки kind
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                file_kind = data.get("kind", "") if isinstance(data, dict) else ""
                if file_kind != kind:
                    continue
            except Exception as exc:  # noqa: BLE001 — скан, не падаем
                warnings.warn(
                    f"find_protocols: не удалось прочитать {yaml_path}: {exc}",
                    stacklevel=2,
                )
                continue
        result[stem] = yaml_path

    return result
