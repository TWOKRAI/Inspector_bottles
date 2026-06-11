"""Декларативная карта регистров устройства.

Мини-DSL, которым сервис устройства (robot_comm, vfd_comm, ...) описывает свою
карту ДАННЫМИ, а не методами с магическими числами:

    MAP = RegisterMap(
        {
            "freq_cmd": Reg(0x1202, scale=100),            # 0.01 Гц на LSB
            "encoder":  RegDW(0x1112, signed=True),        # 32 бита, 2 регистра
            "status":   RegBlock(0x1210, fields=(
                Field("running"),
                Field("out_freq_hz", scale=100),
                Field("current_a", scale=10),
            )),
        },
        word_order="little",
    )

    MAP.read(transport, "encoder")            -> int
    MAP.read(transport, "status")             -> {"running": 0, "out_freq_hz": 50.0, ...}
    MAP.write_ops({"freq_cmd": 50.0, ...})    -> ops для RegisterTransport.transaction()

Масштабирование: новый регистр устройства = одна строка в карте. Encode/decode —
поверх ``sdk/datatypes`` (один источник истины для word order и знаковости).

Семантика scale: в регистре хранится ``value * scale`` (целое); чтение возвращает
``raw / scale`` (float при scale != 1, иначе int). Это соответствует конвенциям
промышленных устройств («частота ×100», «ток ×10»).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

from Services.modbus.sdk.datatypes import (
    WordOrder,
    decode_int16,
    decode_int32,
    decode_uint16,
    decode_uint32,
    encode_int16,
    encode_int32,
    encode_uint16,
    encode_uint32,
)

if TYPE_CHECKING:  # только для аннотаций — без runtime-зависимости
    from Services.modbus.interfaces import RegisterTransport


@dataclass(frozen=True)
class Reg:
    """Одиночный 16-битный регистр.

    Attributes:
        address: Адрес holding-регистра.
        scale:   Множитель хранения: в регистре лежит ``value * scale``.
        signed:  Знаковое 16-битное (two's complement) или беззнаковое.
    """

    address: int
    scale: float = 1.0
    signed: bool = False


@dataclass(frozen=True)
class RegDW:
    """32-битное значение в двух регистрах (DW), порядок слов — из карты.

    Attributes:
        address: Адрес первого регистра пары.
        scale:   Множитель хранения (как у Reg).
        signed:  Знаковое 32-битное или беззнаковое.
    """

    address: int
    scale: float = 1.0
    signed: bool = True


@dataclass(frozen=True)
class Field:
    """Поле внутри блока RegBlock — одно слово блока.

    Attributes:
        name:   Имя ключа в результирующем dict.
        scale:  Множитель хранения слова.
        signed: Знаковое 16-битное слово.
    """

    name: str
    scale: float = 1.0
    signed: bool = False


@dataclass(frozen=True)
class RegBlock:
    """Блок последовательных регистров (телеметрия, статус, конфиг).

    Если заданы ``fields`` — блок читается как dict {имя: значение}, по слову
    на поле (count выводится из их числа). Без fields — сырой list[int].

    Attributes:
        address: Начальный адрес блока.
        count:   Число слов (обязательно, если fields не заданы).
        fields:  Описания слов блока по порядку.
    """

    address: int
    count: int = 0
    fields: tuple[Field, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.fields:
            object.__setattr__(self, "count", len(self.fields))
        if self.count <= 0:
            raise ValueError(f"RegBlock(0x{self.address:04X}): задайте count или fields")


Entry = Union[Reg, RegDW, RegBlock]


def _decode_word(raw: int, *, scale: float, signed: bool) -> int | float:
    """Раскодировать одно слово: знак + масштаб."""
    value = decode_int16(raw) if signed else decode_uint16(raw)
    return value / scale if scale != 1.0 else value


def _encode_word(value: float, *, scale: float, signed: bool) -> int:
    """Закодировать одно слово: масштаб + знак (в u16-представление)."""
    raw = round(value * scale)
    return (encode_int16(raw) if signed else encode_uint16(raw))[0]


class RegisterMap:
    """Карта регистров устройства: чтение/запись по именам через RegisterTransport.

    Карта неизменяема после создания (источник истины протокола устройства);
    word_order применяется ко всем DW-полям карты.
    """

    def __init__(self, entries: dict[str, Entry], *, word_order: WordOrder = "big") -> None:
        if word_order not in ("big", "little"):
            raise ValueError(f"word_order: ожидается 'big' | 'little', получено {word_order!r}")
        self._entries: dict[str, Entry] = dict(entries)
        self._word_order: WordOrder = word_order

    # ------------------------------------------------------------------ #
    # Интроспекция
    # ------------------------------------------------------------------ #

    @property
    def word_order(self) -> WordOrder:
        """Порядок слов для DW-полей карты."""
        return self._word_order

    def names(self) -> list[str]:
        """Имена всех записей карты."""
        return list(self._entries)

    def entry(self, name: str) -> Entry:
        """Описание записи по имени. KeyError с подсказкой при опечатке."""
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Регистр {name!r} отсутствует в карте; есть: {sorted(self._entries)}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    # ------------------------------------------------------------------ #
    # Чтение
    # ------------------------------------------------------------------ #

    def read(self, transport: "RegisterTransport", name: str) -> int | float | dict | list[int]:
        """Прочитать запись карты с устройства и раскодировать.

        Returns:
            Reg      -> int | float (по scale);
            RegDW    -> int | float;
            RegBlock -> dict {field: value} при fields, иначе сырой list[int].
        """
        entry = self.entry(name)
        if isinstance(entry, Reg):
            raw = transport.read_registers(entry.address, 1)[0]
            return _decode_word(raw, scale=entry.scale, signed=entry.signed)
        if isinstance(entry, RegDW):
            regs = transport.read_registers(entry.address, 2)
            decode = decode_int32 if entry.signed else decode_uint32
            value = decode(regs, self._word_order)
            return value / entry.scale if entry.scale != 1.0 else value
        return self._read_block(transport, entry)

    def _read_block(self, transport: "RegisterTransport", block: RegBlock) -> dict | list[int]:
        words = transport.read_registers(block.address, block.count)
        if not block.fields:
            return words
        return {
            f.name: _decode_word(raw, scale=f.scale, signed=f.signed)
            for f, raw in zip(block.fields, words, strict=True)
        }

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def write_ops(self, values: dict[str, float | int | list | dict]) -> list[tuple]:
        """Собрать ops для ``RegisterTransport.transaction()``.

        Порядок ops = порядок ключей ``values`` — вызывающий код управляет
        инвариантом «маркер-флаг последним», ставя флаг последним ключом.

        Args:
            values: имя записи -> значение:
                Reg   <- число;
                RegDW <- число;
                RegBlock <- list значений по порядку слов или dict {field: value}
                           (полный — на каждое поле блока).
        """
        ops: list[tuple] = []
        for name, value in values.items():
            entry = self.entry(name)
            if isinstance(entry, Reg):
                ops.append(("w", entry.address, _encode_word(float(value), scale=entry.scale, signed=entry.signed)))
            elif isinstance(entry, RegDW):
                raw = round(float(value) * entry.scale)
                encode = encode_int32 if entry.signed else encode_uint32
                ops.append(("wm", entry.address, encode(raw, self._word_order)))
            else:
                ops.append(("wm", entry.address, self._encode_block(entry, value)))
        return ops

    def _encode_block(self, block: RegBlock, value: list | dict) -> list[int]:
        if not block.fields:
            words = [int(v) & 0xFFFF for v in value]
            if len(words) != block.count:
                raise ValueError(
                    f"RegBlock(0x{block.address:04X}): ожидается {block.count} слов, получено {len(words)}"
                )
            return words
        if isinstance(value, dict):
            missing = [f.name for f in block.fields if f.name not in value]
            if missing:
                raise ValueError(f"RegBlock(0x{block.address:04X}): не заданы поля {missing}")
            ordered = [value[f.name] for f in block.fields]
        else:
            ordered = list(value)
            if len(ordered) != len(block.fields):
                raise ValueError(
                    f"RegBlock(0x{block.address:04X}): ожидается {len(block.fields)} значений, получено {len(ordered)}"
                )
        return [
            _encode_word(float(v), scale=f.scale, signed=f.signed) for f, v in zip(block.fields, ordered, strict=True)
        ]
