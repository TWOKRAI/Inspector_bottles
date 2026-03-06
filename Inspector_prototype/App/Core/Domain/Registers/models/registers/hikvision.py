# -*- coding: utf-8 -*-
"""
Регистры управления камерой Hikvision.
"""
from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class HikvisionRegisters(RegisterBase):
    """Регистры управления IP-камерой Hikvision."""

    ip: Annotated[
        str,
        FieldMeta(
            "IP-адрес камеры",
            info="IP-адрес Hikvision-камеры в сети.",
            routing={"channel": "control_hikvision"},
        ),
    ] = "192.168.1.64"

    port: Annotated[
        int,
        FieldMeta(
            "Порт подключения",
            info="Порт SDK-подключения к камере (обычно 8000).",
            min=1,
            max=65535,
            routing={"channel": "control_hikvision"},
        ),
    ] = 8000

    username: Annotated[
        str,
        FieldMeta(
            "Имя пользователя",
            info="Имя пользователя для авторизации на камере.",
            routing={"channel": "control_hikvision"},
        ),
    ] = "admin"

    timeout: Annotated[
        float,
        FieldMeta(
            "Таймаут подключения",
            info="Время ожидания подключения к камере.",
            unit="с",
            min=0.5,
            max=30.0,
            round_k=1,
            routing={"channel": "control_hikvision"},
        ),
    ] = 5.0
