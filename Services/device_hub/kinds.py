"""Таблица видов устройств хаба: один источник видов, фабрик драйверов по умолчанию и команд плагина.

Purpose:
    Строка ``DeviceKind`` — вид устройства: ``kind``, префикс команд, классы драйверов по протоколам записи, сборка
    драйвера и операции данных вида. Из ``DEFAULT_KINDS`` выводятся: фабрики драйверов по умолчанию ``DeviceManager``
    (допустимый вид = вид с фабрикой) и источники команд плагина ``command_sources`` — операции читаются из
    ``OP_SPECS`` классов драйверов, кортежи каталога ``spi.py`` напрямую не читаются.
    Путь роста: новый вид = класс драйвера с ``OP_SPECS`` + одна строка ``DEFAULT_KINDS``.
    Направление импортов пакета: ``spi`` <- ``drivers`` <- ``kinds`` <- ``manager`` / плагин.

Public API:
    ``DeviceKind``, ``DriverContext``, ``DEFAULT_KINDS``, ``command_sources``, ``DEFAULT_SOURCES``.

Stability: lite
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.robot_data_ops import param_source_for
from Services.device_hub.spi import ROBOT_DATA_OPS, OpSource, OpSpec

if TYPE_CHECKING:
    from Services.device_hub.registry.entry import DeviceEntry
    from Services.device_hub.spi import DeviceDriver
    from Services.robot_comm.store import RobotDataStore

__all__ = ["DEFAULT_KINDS", "DEFAULT_SOURCES", "DeviceKind", "DriverContext", "command_sources"]

ANY_PROTOCOL = "*"  # ключ ``DeviceKind.drivers``: любой протокол записи, не названный отдельно


@dataclass(frozen=True, slots=True)
class DriverContext:
    """Что менеджер даёт сборке драйвера: снимок на момент создания одного драйвера."""

    publish: Callable[[str, dict], None]
    spawn: Callable[..., Any] | None  # ``IScope.spawn`` области плагина; None — менеджер без области
    robot_store: RobotDataStore | None
    options: Mapping[str, Any]  # опции конструктора вида (``DeviceManager.set_driver_options``)
    resolve_device: Callable[[str], Any]  # драйвер по id (мост ПЧ через транспорт другого устройства)


type DriverBuild = Callable[[type, DeviceEntry, Any, DriverContext], DeviceDriver]


def _build_plain(cls: type, entry: DeviceEntry, proto: Any, ctx: DriverContext) -> DeviceDriver:
    """Сборка по умолчанию: ``cls(entry, proto, **options)``."""
    return cls(entry, proto, **ctx.options)


@dataclass(frozen=True, slots=True)
class DeviceKind:
    """Строка таблицы видов.

    ``drivers`` — протокол записи -> класс драйвера; ключ ``"*"`` — любой другой протокол. Операции команд вида —
    ``OP_SPECS`` этих классов (одноимённые операции разных классов должны быть равны: ``command_table``).
    ``prefix`` — префикс команд ``f"{prefix}_{op}"``; ``None`` — у вида нет сгенерированных команд (тогда ``OP_SPECS``
    классов и ``data_ops`` пусты, иначе ``ValueError`` в ``command_sources``).
    ``data_ops`` — операции данных вида (путь ``data`` плагина, не драйвер).
    ``build`` — ``(класс, entry, protocol, DriverContext) -> драйвер``; по умолчанию
    ``класс(entry, protocol, **options)``.
    """

    kind: str
    drivers: Mapping[str, type]
    prefix: str | None = None
    data_ops: tuple[OpSpec, ...] = ()
    build: DriverBuild = field(default=_build_plain)

    def driver_class(self, protocol: str) -> type:
        """Класс драйвера для протокола записи. ``KeyError`` — протокол не назван и ключа ``"*"`` нет."""
        cls = self.drivers.get(protocol)
        return cls if cls is not None else self.drivers[ANY_PROTOCOL]

    def driver_classes(self) -> tuple[type, ...]:
        """Классы драйверов вида без повторов, в порядке ``drivers``."""
        return tuple(dict.fromkeys(self.drivers.values()))

    def create(self, entry: DeviceEntry, proto: Any, ctx: DriverContext) -> DeviceDriver:
        """Драйвер записи: класс по ``entry.protocol``, сборка ``build``.

        Позднее связывание по модулю класса (``_bound``) — сохранено от фабрики до SPI (она импортировала класс при
        создании драйвера); подмена атрибута модуля допускается только подклассом класса таблицы, иначе ``TypeError``.
        """
        return self.build(_bound(self.driver_class(entry.protocol)), entry, proto, ctx)


def _bound(cls: type) -> type:
    """Класс, привязанный сейчас к имени ``cls`` в модуле, где он определён.

    Прежние фабрики импортировали драйвер при создании, и тесты подменяют класс атрибутом модуля
    (``monkeypatch.setattr(robot_driver_v2, "RobotDriverV2", V2)`` — C-29, SPI). Шов сохранён: подмена действует на
    создание драйвера. Подмена — только подкласс исходного: ``OP_SPECS`` и команды остаются верны, иначе ``TypeError``.
    """
    bound = getattr(sys.modules.get(cls.__module__), cls.__name__, cls)
    if not (isinstance(bound, type) and issubclass(bound, cls)):
        raise TypeError(f"{cls.__module__}.{cls.__name__} подменён не подклассом: {bound!r}")
    return bound


def command_sources(kinds: Sequence[DeviceKind]) -> tuple[OpSource, ...]:
    """Источники команд плагина из таблицы видов: по одному ``OpSource`` на класс драйвера с операциями
    (``route="driver"``, ``ops=cls.OP_SPECS``) и один на ``data_ops`` вида (``route="data"``).

    Pre: виды в ``kinds`` не повторяются.
    Post: порядок — строки таблицы, внутри строки — классы в порядке ``drivers``, затем данные.
    Raises: ``ValueError`` — повтор вида; у вида без префикса есть операции.
    """
    sources: list[OpSource] = []
    seen: set[str] = set()
    for row in kinds:
        if row.kind in seen:
            raise ValueError(f"вид {row.kind!r} повторён в таблице видов")
        seen.add(row.kind)
        driver_ops = [cls.OP_SPECS for cls in row.driver_classes() if cls.OP_SPECS]
        if row.prefix is None:
            if driver_ops or row.data_ops:
                raise ValueError(f"вид {row.kind!r}: операции есть, префикса команд нет")
            continue
        sources += [OpSource(prefix=row.prefix, kind=row.kind, route="driver", ops=ops) for ops in driver_ops]
        if row.data_ops:
            sources.append(OpSource(prefix=row.prefix, kind=row.kind, route="data", ops=row.data_ops))
    return tuple(sources)


def _build_robot_v2(cls: type, entry: DeviceEntry, proto: Any, ctx: DriverContext) -> DeviceDriver:
    """Робот протокола v2: потоки — только в области плагина (T5.3 круг 2); параметры — из params.yaml (T5.3c c2)."""
    if ctx.spawn is None:
        raise RuntimeError(f"робот {entry.id!r} (delta_v2): менеджер без spawn не создаёт драйвер v2")
    if ctx.robot_store is None:
        return cls(entry, proto, publish=ctx.publish, spawn=ctx.spawn, **ctx.options)
    # Плохие данные бросают RobotDataInvalid и др. из фабрики, их перехватывает ``connect``
    param_source = param_source_for(ctx.robot_store, entry.id, entry.params)
    return cls(
        entry,
        proto,
        publish=ctx.publish,
        spawn=ctx.spawn,
        param_source=param_source,
        store=ctx.robot_store,
        **ctx.options,
    )


def _build_robot(cls: type, entry: DeviceEntry, proto: Any, ctx: DriverContext) -> DeviceDriver:
    """Робот: класс v2 — своя сборка, v1 — по умолчанию."""
    if issubclass(cls, RobotDriverV2):
        return _build_robot_v2(cls, entry, proto, ctx)
    return _build_plain(cls, entry, proto, ctx)


def _build_vfd(cls: type, entry: DeviceEntry, proto: Any, ctx: DriverContext) -> DeviceDriver:
    """ПЧ: транспорт может идти через другое устройство (``resolve_device``)."""
    return cls(entry, proto, resolve_device=ctx.resolve_device, **ctx.options)


# Встроенные виды хаба. Порядок строк и классов задаёт порядок команд плагина.
DEFAULT_KINDS: tuple[DeviceKind, ...] = (
    DeviceKind(
        kind="robot",
        drivers={"delta_v2": RobotDriverV2, ANY_PROTOCOL: RobotDriver},
        prefix="robot",
        data_ops=ROBOT_DATA_OPS,
        build=_build_robot,
    ),
    DeviceKind(kind="vfd", drivers={ANY_PROTOCOL: VfdDriver}, prefix="vfd", build=_build_vfd),
    DeviceKind(kind="hikvision", drivers={ANY_PROTOCOL: HikvisionDriver}, prefix="hik"),  # hik_* — ручные команды
    DeviceKind(kind="generic_modbus", drivers={ANY_PROTOCOL: GenericModbusDriver}),
)

# Источники команд плагина хаба по умолчанию (55 команд robot_* / vfd_*)
DEFAULT_SOURCES: tuple[OpSource, ...] = command_sources(DEFAULT_KINDS)
