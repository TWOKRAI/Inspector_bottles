# -*- coding: utf-8 -*-
"""Контракт порта камеры: типы, ошибка, `DeviceSdk` и `DevicePort` (Task 1.5).

Только stdlib: ни `numpy`, ни `cv2`, ни Qt, ни `multiprocess_framework`. Любой драйвер
(MvCodeReader, MVS, OpenCV, будущий) реализует `DevicePort` и проходит один контрактный набор
`Services/camera_device/tests/port_contract.py`.

Состояния порта: `closed -> opened -> grabbing -> opened -> closed`.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, runtime_checkable

type IdentKind = Literal["serial", "ip", "url", "index"]
type ErrorKind = Literal["busy", "not_found", "network", "access", "range", "closed", "timeout", "other"]
# Событие связи прибора (W2-a): `disconnected` — прибор сообщил об обрыве; `other` — прочие события драйвера.
type LinkEvent = Literal["disconnected", "other"]


@dataclass(frozen=True)
class DeviceIdentity:
    """Как найти прибор: `kind` из `serial|ip|url|index`, `value` — строка, `name` — подпись для людей."""

    kind: IdentKind
    value: str
    name: str = ""


@dataclass(frozen=True)
class DeviceInfo:
    """Личность открытого прибора: запись перечисления SDK плюс формат кадра.

    Пустые строки и `0` — «неизвестно» (USB, фейк без сети). `enum_matches` — сколько записей перечисления
    совпало с `DeviceIdentity` при открытии, `enum_list` — их тексты (`entry_text`) в порядке SDK.
    """

    serial: str
    model: str = ""
    ip: str = ""
    mask: str = ""
    host_ip: str = ""
    mac: str = ""
    pixel_format: str = ""
    width: int = 0
    height: int = 0
    enum_matches: int = 1
    enum_list: tuple[str, ...] = ()


@dataclass(frozen=True)
class Binding:
    """Привязка параметра к узлу прибора.

    `kind` описательный (например `"genicam"`), ядро по нему не ветвится. `vtype` — `"int"`, `"float"`,
    `"enum"`, `"bool"` и прочие строки записей (`"string"`, `"command"`); не валидируется.
    `eps_abs` — допуск сравнения прочитанного с записанным для float.
    """

    kind: str
    key: str
    vtype: str
    eps_abs: float = 1e-6


@dataclass(frozen=True)
class ParamInfo:
    """Описание узла: границы, шаг, имена enum и доступ (`RW|RO|WO|NA|NI`)."""

    min: float | int | None
    max: float | int | None
    inc: float | int | None
    entries: tuple[str, ...] | None
    access: str


@dataclass
class RawFrame:
    """Кадр, скопированный из буфера SDK.

    `data` — `bytearray`, а не `bytes`: потребитель кладёт его в numpy без копии, владелец буфера — вызывающий.
    `lost_packets` — сколько пакетов потеряно в этом кадре (`0` — кадр цел или драйвер не знает);
    `trigger_index` — счётчик срабатываний триггера прибора (`None` — драйвер его не даёт).
    """

    data: bytearray
    width: int
    height: int
    pixel_format: str
    frame_num: int
    extras: dict = field(default_factory=dict)
    lost_packets: int = 0
    trigger_index: int | None = None


class PortError(Exception):
    """Ошибка порта. Текст НЕ содержит записываемого значения: в логи идут `where`, `kind`, `code`.

    `timeout` бросают только `open` и `execute`; `get_frame` по таймауту возвращает `None`.
    """

    def __init__(self, kind: ErrorKind, where: str, code: int | None = None) -> None:
        self.kind: ErrorKind = kind
        self.where: str = where
        self.code: int | None = code
        code_text = "" if code is None else f" code=0x{code:08X}"
        super().__init__(f"{where}: {kind}{code_text}")


class AmbiguousDeviceError(PortError):
    """Перечисление дало несколько записей по одной личности, и ни одна не в подсети камеры.

    Для вызывающего это `PortError("not_found", "open")`; `entries` — тексты записей (`entry_text`) в порядке SDK.
    Адрес прибора в тексте — не записываемое значение узла (рецепт может нести секрет, адрес — нет).
    """

    def __init__(self, ident: DeviceIdentity, entries: tuple[str, ...]) -> None:
        PortError.__init__(self, "not_found", "open")
        self.entries = entries
        text = (
            f"open: not_found: неоднозначное перечисление {ident.kind}={ident.value} записей={len(entries)}, "
            f"ни одна запись не в подсети камеры; записи: {' | '.join(entries)}"
        )
        Exception.__init__(self, text)


def entry_text(e: DeviceInfo) -> str:
    """Запись перечисления одной строкой: `ip=... mask=... host_ip=... mac=...` (для лога и `enum_list`)."""
    return f"ip={e.ip} mask={e.mask} host_ip={e.host_ip} mac={e.mac}"


def in_camera_subnet(e: DeviceInfo) -> bool | None:
    """Лежат ли камера и сетевая карта хоста в одной подсети.

    Returns:
        `None` — подсеть неизвестна: `ip`, `mask` или `host_ip` не разбирается как IPv4 (USB, фейк без сети) либо
        маска `0.0.0.0`; иначе `ip & mask == host_ip & mask`.
    """
    try:
        ip = int(ipaddress.IPv4Address(e.ip))
        mask = int(ipaddress.IPv4Address(e.mask))
        host_ip = int(ipaddress.IPv4Address(e.host_ip))
    except ValueError:
        return None
    if mask == 0:  # иначе "в подсети" оказался бы любой хост: подсеть неизвестна, а не подтверждена
        return None
    return ip & mask == host_ip & mask


def select_device(ident: DeviceIdentity, entries: Sequence[DeviceInfo]) -> tuple[int, DeviceInfo]:
    """Выбрать запись перечисления под личность. Один прибор может быть перечислен несколько раз (по карте на сеть).

    Pre: `entries` — перечисление одного вызова SDK, порядок SDK.
    Post: возврат — индекс выбранной записи во входном списке и её копия с `enum_matches` (сколько записей
        совпало) и `enum_list` (их `entry_text`); вход не меняется. Одно совпадение берётся как есть; несколько —
        из тех, что в подсети камеры, меньший `host_ip` (при равенстве меньший индекс). Нет совпадений —
        `PortError("not_found", "open")`; несколько, и ни одна не в подсети — `AmbiguousDeviceError`.
        Совпадение: `serial` -> `serial`, `ip` -> `ip`, `index` -> запись с этим номером, прочие `kind` — пусто.
    """
    if ident.kind == "serial":
        matches = [(i, e) for i, e in enumerate(entries) if e.serial == ident.value]
    elif ident.kind == "ip":
        matches = [(i, e) for i, e in enumerate(entries) if e.ip == ident.value]
    elif ident.kind == "index":
        try:
            position = int(ident.value)
        except ValueError:
            raise PortError("not_found", "open") from None
        matches = [(i, e) for i, e in enumerate(entries) if i == position] if position >= 0 else []
    else:
        matches = []
    if not matches:
        raise PortError("not_found", "open")
    texts = tuple(entry_text(e) for _, e in matches)
    if len(matches) == 1:
        chosen_index, chosen = matches[0]
    else:
        in_net = [(i, e) for i, e in matches if in_camera_subnet(e) is True]
        if not in_net:
            raise AmbiguousDeviceError(ident, texts)

        # `min` при равном ключе берёт первый (меньший индекс); `host_ip` разобран: `in_camera_subnet` не `None`
        def host_key(pair: tuple[int, DeviceInfo]) -> int:
            return int(ipaddress.IPv4Address(pair[1].host_ip))

        chosen_index, chosen = min(in_net, key=host_key)
    return chosen_index, replace(chosen, enum_matches=len(matches), enum_list=texts)


@runtime_checkable
class DeviceSdk(Protocol):
    """Жизненный цикл SDK вендора: счётчик ссылок и перечисление приборов."""

    def acquire(self) -> None:
        """Взять ссылку на SDK; первая ссылка инициализирует его.

        Pre: нет.
        Post: счётчик ссылок увеличен на 1.
        """
        ...

    def release(self) -> None:
        """Отдать ссылку на SDK; последняя ссылка финализирует его.

        Pre: счётчик ссылок > 0, иначе `RuntimeError`.
        Post: счётчик ссылок уменьшен на 1.
        """
        ...

    def enum_devices(self) -> list[DeviceIdentity]:
        """Перечислить доступные приборы.

        Pre: SDK взят через `acquire()`.
        Post: список `DeviceIdentity` (может быть пустым), состояние SDK не изменено.
        """
        ...


@runtime_checkable
class DevicePort(Protocol):
    """Порт одного прибора. Все вызовы — из одного потока (поток-владелец сеанса).

    Invariants:
        - Состояния: `closed -> opened -> grabbing -> opened -> closed`.
        - `get_param`, `set_param`, `describe_param`, `execute`, `start_grabbing` вне `opened`/`grabbing`
          бросают `PortError(kind="closed")`; `get_frame` вне `grabbing` — тоже.
        - Идемпотентны (не бросают): `close()` в любом состоянии, `stop_grabbing()` вне `grabbing`,
          `start_grabbing()` в `grabbing`.
        - Текст `PortError` не содержит записываемого значения.
        - `capabilities` не меняется за время жизни порта; ядро ветвится только по
          `read_back`, `live_write`, `node_describe`, `software_trigger`, `restart_regrab`
          (другие значения драйвер объявлять вправе, их не проверяют).
    """

    capabilities: frozenset[str]
    # Личность открытого прибора. `None` у созданного порта и после `close`; ставит `open` (до возврата из него).
    device_info: DeviceInfo | None

    def open(self, ident: DeviceIdentity) -> None:
        """Открыть прибор.

        Pre: порт в состоянии `closed`.
        Post: порт в состоянии `opened`, `device_info` поставлен (драйвер, не умеющий отдать личность, оставляет
            `None`); ошибки — `PortError` (`busy`, `not_found`, `network`, `access`, `timeout`).
        """
        ...

    def get_param(self, b: Binding) -> object:
        """Прочитать значение узла.

        Pre: порт `opened` или `grabbing`, узел доступен на чтение.
        Post: значение узла; состояние порта и прибора не изменено; закрытый узел — `PortError(kind="access")`.
        """
        ...

    def set_param(self, b: Binding, value: object) -> None:
        """Записать значение узла.

        Pre: порт `opened` или `grabbing`; при `grabbing` запись разрешена только узлам, живым при захвате.
        Post: узел хранит значение (с коррекцией шага прибором); при отказе — `PortError` без значения в тексте.
        """
        ...

    def describe_param(self, b: Binding) -> ParamInfo | None:
        """Описать узел: границы, шаг, имена enum, доступ.

        Pre: порт `opened` или `grabbing`.
        Post: `ParamInfo`; `None`, если `"node_describe"` не в `capabilities`; закрытый узел не бросает.
        """
        ...

    def execute(self, b: Binding) -> None:
        """Выполнить команду-узел (например программный триггер).

        Pre: порт `opened` или `grabbing`; `"software_trigger"` в `capabilities`.
        Post: команда выполнена; без `software_trigger` — `PortError(kind="access")`.
        """
        ...

    def start_grabbing(self) -> None:
        """Начать захват кадров.

        Pre: порт `opened` или `grabbing`.
        Post: порт `grabbing`; повторный вызов в `grabbing` ничего не делает.
        """
        ...

    def get_frame(self, timeout_ms: int) -> RawFrame | None:
        """Забрать кадр.

        Pre: порт `grabbing`, иначе `PortError(kind="closed")`.
        Post: `RawFrame` — копия, буфер SDK освобождён до возврата; `None` по таймауту (не исключение).
        """
        ...

    def stop_grabbing(self) -> None:
        """Остановить захват кадров.

        Pre: нет (в любом состоянии).
        Post: порт не в `grabbing`; вне `grabbing` ничего не делает.
        """
        ...

    def close(self) -> None:
        """Закрыть прибор.

        Pre: нет (в любом состоянии).
        Post: порт `closed`; повторный вызов ничего не делает.
        """
        ...


@runtime_checkable
class LinkEventSource(Protocol):
    """Необязательная способность порта (W2-a): события связи прибора. В `DevicePort` член не входит.

    Сеанс проверяет её через `isinstance(port, LinkEventSource)`; порт без метода — источник событий не даёт.
    """

    def drain_link_events(self) -> list[LinkEvent]:
        """Забрать события связи, пришедшие с прошлого вызова.

        Pre: зовёт только поток-владелец сеанса (как и остальные методы порта).
        Post: не блокирует; возврат — события по порядку прихода (пустой список — событий нет), очередь пуста.
            Очередь живёт с портом, а не с сеансом прибора: сеанс вычитывает и ОТБРАСЫВАЕТ события перед
            `start_grabbing` каждой попытки (события прошлого сеанса прибора устарели).
        """
        ...
