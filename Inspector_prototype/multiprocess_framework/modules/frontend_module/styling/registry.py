# -*- coding: utf-8 -*-
"""
Именованные стили: шаблон QSS + токены по умолчанию (слой между глобальным и виджетом).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union

from frontend_module.styling.qss_utils import load_qss_file

PathLike = Union[str, Path]


@dataclass
class NamedStyleBundle:
    """Именованный стиль: текст шаблона и дефолтные токены (часть «стиля по id»)."""

    template: str
    default_tokens: Dict[str, Any] = field(default_factory=dict)


class NamedStyleRegistry:
    """
    Реестр `style_id → шаблон + default_tokens`.

    Регистрация пути к файлу: шаблон читается при вызове `register_path` (копия в память).
    """

    def __init__(self) -> None:
        self._bundles: Dict[str, NamedStyleBundle] = {}

    def register(
        self,
        name: str,
        template: str,
        default_tokens: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._bundles[name] = NamedStyleBundle(
            template=template,
            default_tokens=dict(default_tokens) if default_tokens else {},
        )

    def register_path(
        self,
        name: str,
        path: PathLike,
        default_tokens: Optional[Dict[str, Any]] = None,
        *,
        encoding: str = "utf-8",
    ) -> None:
        text = load_qss_file(path, encoding=encoding)
        self.register(name, text, default_tokens)

    def get(self, name: str) -> Optional[NamedStyleBundle]:
        return self._bundles.get(name)

    def has(self, name: str) -> bool:
        return name in self._bundles

    def names(self) -> list[str]:
        return list(self._bundles.keys())

    def merge_default_tokens(self, name: str, partial: Dict[str, Any]) -> bool:
        """
        Дописать токены именованного стиля (для UiThemeConfig.bundle_overrides).

        Returns:
            True если стиль существует.
        """
        b = self._bundles.get(name)
        if b is None:
            return False
        b.default_tokens.update(partial)
        return True
