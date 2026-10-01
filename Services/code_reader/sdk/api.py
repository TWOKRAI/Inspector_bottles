# -*- coding: utf-8 -*-
"""Тонкая обёртка над ``MvCodeReaderCtrl.dll``: перечисление, открытие, захват кадра.

Последовательность SDK: ``EnumDevices`` → ``CreateHandle`` → ``OpenDevice`` →
``StartGrabbing`` → цикл ``GetOneFrameTimeoutEx2`` → ``StopGrabbing`` → ``CloseDevice``
→ ``DestroyHandle``. Логики сессии (поток, повторы, состояния) здесь нет — это
``core/`` (Task 6.2).

DLL грузится лениво, при первом вызове: конструктор без SDK не падает.
Коды возврата сравниваются без знака (``rc & 0xFFFFFFFF``): ctypes по умолчанию
отдаёт ``c_int`` со знаком.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from typing import Any

from .errors import E_NODATA, MV_OK, SdkError, unsigned
from .loader import load_library
from .structures import (
    BCR_INFO_EX2,
    DEVICE_INFO,
    DEVICE_INFO_LIST,
    GIGE_DEVICE,
    IMAGE_OUT_INFO_EX2,
    MAX_BCR_COUNT_EX,
    MAX_DEVICE_NUM,
)

_PREFIX = "MV_CODEREADER_"


@dataclass(frozen=True)
class DeviceEntry:
    """Найденный прибор. ``info`` — КОПИЯ ``DEVICE_INFO``: память списка SDK живёт до следующего EnumDevices."""

    ip: str
    model: str
    serial: str
    info: DEVICE_INFO


@dataclass(frozen=True)
class RawFrame:
    """Кадр SDK, скопированный из буферов SDK (они переиспользуются на следующем GetOneFrame).

    ``image`` — сырые байты кадра длины ``nFrameLen`` (JPEG или Mono8, см. ``pixel_type``);
    ``codes`` — копии записей ``BCR_INFO_EX2``, по одной на ``nCodeNum``.
    """

    image: bytes
    width: int
    height: int
    pixel_type: int
    trigger_index: int
    frame_num: int
    no_read_num: int
    codes: tuple[BCR_INFO_EX2, ...]


def _handle(h: Any) -> C.c_void_p:
    """Handle как ``c_void_p``: голый int без argtypes ctypes обрезал бы до 32 бит."""
    return C.c_void_p(int(getattr(h, "value", h) or 0))


def _text(raw: Any) -> str:
    return bytes(raw).split(b"\0", 1)[0].decode("utf-8", "replace")


def _ip(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


class MvCodeReaderApi:
    """Вызовы SDK один к одному; ненулевой код → ``SdkError``, кроме ``E_NODATA`` в ``get_frame``."""

    def __init__(self, lib: Any = None) -> None:
        self._lib = lib

    def _call(self, name: str, *args: Any) -> int:
        if self._lib is None:
            self._lib = load_library()
        return unsigned(getattr(self._lib, _PREFIX + name)(*args))

    def _check(self, name: str, *args: Any) -> None:
        rc = self._call(name, *args)
        if rc != MV_OK:
            raise SdkError(rc, _PREFIX + name)

    def enum_devices(self) -> list[DeviceEntry]:
        lst = DEVICE_INFO_LIST()
        self._check("EnumDevices", C.byref(lst), C.c_uint(GIGE_DEVICE))
        entries: list[DeviceEntry] = []
        for i in range(min(lst.nDeviceNum, MAX_DEVICE_NUM)):
            ptr = lst.pDeviceInfo[i]
            if not ptr:
                continue
            info = DEVICE_INFO.from_buffer_copy(ptr.contents)
            gige = info.SpecialInfo.stGigEInfo
            entries.append(
                DeviceEntry(
                    ip=_ip(gige.nCurrentIp),
                    model=_text(gige.chModelName),
                    serial=_text(gige.chSerialNumber),
                    info=info,
                )
            )
        return entries

    def open(self, entry: DeviceEntry) -> int:
        """``CreateHandle`` + ``OpenDevice``; при отказе OpenDevice handle уничтожается здесь же."""
        handle = C.c_void_p()
        # Копия, не указатель в буфер EnumDevices: так же делает вендорский
        # Demo/VC/ConnectSpecCamera (DEVICE_INFO со стека), и копия переживает повторный Enum.
        self._check("CreateHandle", C.byref(handle), C.byref(entry.info))
        h = handle.value or 0
        rc = self._call("OpenDevice", _handle(h))
        if rc != MV_OK:
            # У вызывающего handle ещё нет — убрать его больше некому.
            rc_destroy = self._call("DestroyHandle", _handle(h))
            exc = SdkError(rc, _PREFIX + "OpenDevice")
            if rc_destroy != MV_OK:
                # Не терять: handle мог остаться внутри SDK (ревью 6.1, п.3).
                exc.add_note(f"DestroyHandle после отказа тоже вернул 0x{rc_destroy:08X}")
            raise exc
        return h

    def start_grabbing(self, h: Any) -> None:
        self._check("StartGrabbing", _handle(h))

    def stop_grabbing(self, h: Any) -> None:
        self._check("StopGrabbing", _handle(h))

    def close(self, h: Any) -> None:
        """``CloseDevice``, затем ``DestroyHandle`` — второй зовётся, даже если первый упал."""
        try:
            self._check("CloseDevice", _handle(h))
        finally:
            self._check("DestroyHandle", _handle(h))

    def get_frame(self, h: Any, timeout_ms: int) -> RawFrame | None:
        """Один вызов ``GetOneFrameTimeoutEx2``: ``None`` ровно на ``E_NODATA``, иначе кадр-копия."""
        pdata = C.POINTER(C.c_ubyte)()
        info = IMAGE_OUT_INFO_EX2()
        rc = self._call("GetOneFrameTimeoutEx2", _handle(h), C.byref(pdata), C.byref(info), C.c_uint(timeout_ms))
        if rc == E_NODATA:
            return None
        if rc != MV_OK:
            raise SdkError(rc, _PREFIX + "GetOneFrameTimeoutEx2")

        image = C.string_at(pdata, info.nFrameLen) if pdata and info.nFrameLen else b""
        codes: tuple[BCR_INFO_EX2, ...] = ()
        no_read = 0
        result_ptr = info.UnparsedBcrList.pstCodeListEx2
        if result_ptr:
            result = result_ptr.contents  # вид на буфер SDK, не копия — копируем по записи
            count = min(result.nCodeNum, MAX_BCR_COUNT_EX)
            codes = tuple(BCR_INFO_EX2.from_buffer_copy(result.stBcrInfoEx2[i]) for i in range(count))
            no_read = result.nNoReadNum
        return RawFrame(
            image=image,
            width=info.nWidth,
            height=info.nHeight,
            pixel_type=info.enPixelType,
            trigger_index=info.nTriggerIndex,
            frame_num=info.nFrameNum,
            no_read_num=no_read,
            codes=codes,
        )
