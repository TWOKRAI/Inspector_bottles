# -*- coding: utf-8 -*-
"""
RegisterDispatchMeta — куда отправлять register_update с GUI для целого регистра.

Задаётся как атрибут класса схемы (не поле модели):

    class MyRegisters(SchemaBase):
        register_dispatch = RegisterDispatchMeta(process_targets=("renderer",))

См. docs/ROUTING_GLOSSARY.md (fan-out, отличие от FieldRouting.channel).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterDispatchMeta:
    """
    Имена процессов для доставки изменений регистра (register_update).

    process_targets:
        Кортеж имён в порядке вызова send_message. Пустой кортеж — доставка
        только через connection_map / process_targets на уровне поля (FieldRouting).
    """

    process_targets: tuple[str, ...] = ()
