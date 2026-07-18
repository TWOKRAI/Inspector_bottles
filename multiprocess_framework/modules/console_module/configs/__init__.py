# -*- coding: utf-8 -*-
# ConsoleProcessConfig переехал в process_module/configs/ (Фаза 2 framework-layer-grouping,
# K1: артефакт запуска процесса, не собственность консоли; убирает import-time цикл
# console_module → process_module).
from .console_config import ConsoleConfig

__all__ = ["ConsoleConfig"]
