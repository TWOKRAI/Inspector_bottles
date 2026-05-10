# -*- coding: utf-8 -*-
"""
action_log_setup — создание таблицы action_log через SQLManager.

Использует SQLManager.create_tables() с ActionLogRow,
что автоматически генерирует DDL через DDLBuilder + SchemaBaseMapper.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.sql_module.core.sql_manager import SQLManager

from multiprocess_prototype.frontend.actions.persistence.schema_ext import ActionLogRow


def create_action_log_table(sql_manager: "SQLManager") -> None:
    """Создать таблицу action_log (IF NOT EXISTS).

    Вызывать при инициализации DatabaseProcess,
    после того как SQLManager уже инициализирован.

    Args:
        sql_manager: инициализированный экземпляр SQLManager.
    """
    sql_manager.create_tables([ActionLogRow])
