# -*- coding: utf-8 -*-
"""
LabelConfig — настройки отображения подписи.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from frontend_module.components.base.config import BaseControlConfig


@dataclass
class LabelConfig(BaseControlConfig):
    """Настройки подписи (позиция, видимость). Текст подставляется в setup()."""

    position: Literal["left", "right", "top", "bottom"] = "left"
    visible: bool = True
