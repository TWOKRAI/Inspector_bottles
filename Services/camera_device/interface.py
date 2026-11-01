# -*- coding: utf-8 -*-
"""Контракт порта камеры: типы, ошибка, `DeviceSdk` и `DevicePort` (Task 1.5).

Только stdlib: ни `numpy`, ни `cv2`, ни Qt, ни `multiprocess_framework`. Любой драйвер
(MvCodeReader, MVS, OpenCV, будущий) реализует `DevicePort` и проходит один контрактный набор
`Services/camera_device/tests/port_contract.py`.

Состояния порта: `closed -> opened -> grabbing -> opened -> closed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

type IdentKind = Literal["serial", "ip", "url", "index"]
type ErrorKind = Literal["busy", "not_found", "network", "access", "range", "closed", "timeout", "other"]


@dataclass(frozen=True)
class DeviceIdentity:
    """Как найти прибор: `kind` из `serial|ip|url|index`, `value` — строка, `name` — подпись для людей."""

    kind: IdentKind
    value: str
    name: str = ""


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
    """

    data: bytearray
    width: int
    height: int
    pixel_format: str
    frame_num: int
    extras: dict = field(default_factory=dict)


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

    def open(self, ident: DeviceIdentity) -> None:
        """Открыть прибор.

        Pre: порт в состоянии `closed`.
        Post: порт в состоянии `opened`; ошибки — `PortError` (`busy`, `not_found`, `network`, `access`, `timeout`).
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
