# -*- coding: utf-8 -*-
"""Коды возврата MvCodeReader SDK и исключения слоя ``sdk/``.

Коды SDK — 32-битные беззнаковые (``0x8002....``); ctypes с ``restype = c_int``
отдаёт их со знаком, поэтому всё сравнение идёт через ``code & 0xFFFFFFFF``.
"""

from __future__ import annotations

MV_OK = 0
# «Кадра за таймаут не было» — нормальный исход GetOneFrameTimeoutEx2, не ошибка.
E_NODATA = 0x80020006
# Прибор занят другим клиентом (IDMVS): доступ эксклюзивный.
E_ACCESS_DENIED = 0x80020203


def unsigned(code: int) -> int:
    """Код возврата SDK как беззнаковое 32-битное число."""
    return int(code) & 0xFFFFFFFF


class SdkError(Exception):
    """Вызов SDK вернул ненулевой код.

    ``code`` — беззнаковый 32-бит, ``where`` — имя вызова (``MV_CODEREADER_OpenDevice``).
    """

    def __init__(self, code: int, where: str) -> None:
        self.code = unsigned(code)
        self.where = where
        super().__init__(f"{where} вернул 0x{self.code:08X}")


class SdkNotFoundError(Exception):
    """Каталог с ``MvCodeReaderCtrl.dll`` не найден или платформа не Windows."""
