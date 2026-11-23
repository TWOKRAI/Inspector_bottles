# -*- coding: utf-8 -*-
"""Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов

Сервис промышленного считывателя кодов Hikrobot ID3000 (MV-ID3013PM-06M).

Внешние модули зависят только от `Services.code_reader.interfaces`.
Настройка прибора и все снятые с железа тонкости — `docs/SETUP.md`.
"""

from Services.code_reader.core import (
    ReadResult,
    ReadStatus,
    ResultSink,
    parse_packet,
    split_stream,
)

__all__ = ["ReadResult", "ReadStatus", "ResultSink", "parse_packet", "split_stream"]
