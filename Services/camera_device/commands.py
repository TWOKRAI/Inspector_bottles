# -*- coding: utf-8 -*-
"""Модели аргументов команд плагина камеры (Task 2.3c, module contract lite).

Purpose:
    Форма `data` команд `take_device`, `release_device`, `apply_params`. Модели разбирает сам обработчик
    (`model_validate`): до Task 1.3 framework `data` не валидирует. Модель, объявляющая параметр,
    который обработчик не читает, лгала бы в `params_schema` (1.3), поэтому `timeout_s` читают обе команды.

Public API:
    TakeDeviceArgs(timeout_s=5.0)     — срок `DeviceSession.start`, с; `0 < timeout_s <= 30.0`
    ReleaseDeviceArgs(timeout_s=2.0)  — срок `DeviceSession.stop`, с; `0 < timeout_s <= 30.0`
    ApplyParamsArgs(params)           — пакет «поле register'а -> значение»; лишние ключи запрещены

Stability:
    Имена и поля моделей читают Task 1.3 (`command_contracts`) и Task 4.2a: менять только вместе с ними.
    Умолчания сроков совпадают с `_START_TIMEOUT_S`/`_STOP_TIMEOUT_S` плагина. У `TakeDeviceArgs` и
    `ReleaseDeviceArgs` лишние ключи `data` игнорируются (как до задачи), у `ApplyParamsArgs` — запрещены.

Слой: Services -> pydantic (стороннее), framework не нужен.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ApplyParamsArgs", "ReleaseDeviceArgs", "TakeDeviceArgs"]

# Верхняя граница срока: системный поток процесса ждёт `start`/`stop` весь срок (`timeout_s=3600` держал бы его час).
_MAX_TIMEOUT_S = 30.0


class TakeDeviceArgs(BaseModel):
    """`take_device`: срок ожидания открытия прибора, с."""

    timeout_s: float = Field(5.0, gt=0, le=_MAX_TIMEOUT_S)


class ReleaseDeviceArgs(BaseModel):
    """`release_device`: срок ожидания остановки и закрытия, с."""

    timeout_s: float = Field(2.0, gt=0, le=_MAX_TIMEOUT_S)


class ApplyParamsArgs(BaseModel):
    """`apply_params`: пакет `{поле register'а: значение}`; порядок словаря = порядок записи."""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any]
