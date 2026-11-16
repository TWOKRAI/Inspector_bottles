# -*- coding: utf-8 -*-
"""Ключи работы системы в конфиге PM одной моделью (Task 2.7 S3b1, ADR-PMM-049).

``RunConfig`` — единственное место, где описаны ключи ``run_gate`` / ``run_autostart`` / ``run_stop_timeout_s`` /
``run_restart_grace_s``: тип, умолчание, проверка. PM читает значение через ``run_config_value`` (годное значение
или умолчание + признак «негодно»); прототип наследует модель (``SystemConfig(RunConfig)``), а не копирует поля.

Чистый модуль без IO: часов, логгера и процессов нет.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StrictBool, ValidationError

from ...data_schema_module import SchemaBase

#: Положительное конечное число; ``strict`` — ``True`` и ``"2"`` не проходят (``PositiveFloat`` их пропускает).
type _PositiveSeconds = Annotated[float, Field(gt=0, strict=True, allow_inf_nan=False)]


class RunConfig(SchemaBase):
    """Ключи работы PM (плоские): гейт работы, автостарт, срок остановки, окно перезапуска."""

    run_gate: StrictBool = False
    run_autostart: StrictBool = False
    run_stop_timeout_s: _PositiveSeconds = 10.0
    run_restart_grace_s: _PositiveSeconds = 30.0


#: Имена ключей ``RunConfig`` в порядке полей.
RUN_CONFIG_KEYS: tuple[str, ...] = tuple(RunConfig.model_fields)


def run_config_value(key: str, raw: object) -> tuple[object, bool]:
    """Значение ключа ``RunConfig`` из сырого конфига: ``(значение, годно)``; не бросает на негодном значении.

    ``raw is None`` (ключа нет) -> ``(умолчание поля, True)``; годное -> ``(значение, True)``; негодное ->
    ``(умолчание поля, False)``. Значение входа в результат и в сообщения не попадает (ADR-PMM-044 п.1).
    Ключ не из ``RUN_CONFIG_KEYS`` — ошибка вызывающего (``KeyError``).
    """
    default = RunConfig.model_fields[key].default
    if raw is None:
        return default, True
    try:
        model = RunConfig.model_validate({key: raw})
    except ValidationError:
        return default, False
    return getattr(model, key), True
