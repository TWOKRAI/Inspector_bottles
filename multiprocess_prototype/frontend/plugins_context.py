# -*- coding: utf-8 -*-
"""PluginsContext — связка зависимостей plugins domain.

Сейчас содержит только PluginRegistry, но структура выбрана единообразно
с другими контекстами — добавление новых зависимостей пройдёт
без смены сигнатур потребителей.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginsContext:
    """Plugins-домен: реестр плагинов.

    Attributes:
        registry: PluginRegistry (vocabulary плагинов).
            Тип `Any` потому что реестр живёт в `Plugins/` пакете
            и импортируется only-on-wire (избегаем тяжёлой зависимости).
    """

    registry: Any
