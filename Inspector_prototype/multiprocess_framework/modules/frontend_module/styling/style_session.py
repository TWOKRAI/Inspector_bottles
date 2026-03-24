# -*- coding: utf-8 -*-
"""
Сессия стилей: глобальные токены, опционально глобальный QSS на QApplication,
регистрация виджетов с каскадом слоёв и refresh по style_id.

Слой токенов (порядок merge, слабее → сильнее):
`style_id` defaults → `global_tokens` → `widget_layer` → `component_layer`.
Так глобальная палитра перекрывает дефолты именованного стиля, а виджет/компонент — палитру.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from frontend_module.core.qt_imports import QApplication, QWidget
from frontend_module.styling.qss_utils import (
    merge_token_layers,
    minimal_fallback_qss,
    render_qss,
    resolve_template,
)
from frontend_module.styling.registry import NamedStyleRegistry

PathLike = Union[str, Path]


@dataclass
class _Registration:
    reg_id: int
    wref: weakref.ReferenceType[QWidget]
    style_id: str
    template: Optional[str]
    template_path: Optional[str]
    widget_layer: Dict[str, Any]
    component_layer: Dict[str, Any]


class StyleSession:
    """
    Управление живыми стилями: глобальная палитра, именованные стили, переопределения
    на уровне виджета и компонента.

    - `set_global_tokens` / `update_global_tokens` — база для всех зарегистрированных виджетов.
    - `register(...)` — привязать виджет к шаблону и слоям; возвращает registration_id.
    - `refresh(style_id=None)` — пересчитать QSS только для данного style_id или для всех.
    """

    def __init__(self, registry: Optional[NamedStyleRegistry] = None) -> None:
        self._registry = registry or NamedStyleRegistry()
        self._global_tokens: Dict[str, Any] = {}
        self._global_qss: Optional[str] = None
        self._next_id = 1
        self._entries: List[_Registration] = []

    @property
    def registry(self) -> NamedStyleRegistry:
        return self._registry

    def set_global_tokens(self, tokens: Dict[str, Any]) -> None:
        self._global_tokens = dict(tokens)

    def update_global_tokens(self, partial: Dict[str, Any]) -> None:
        self._global_tokens.update(partial)

    def get_global_tokens(self) -> Dict[str, Any]:
        return dict(self._global_tokens)

    def set_global_qss(self, qss: Optional[str]) -> None:
        """Опционально: один QSS на всё приложение (например базовые шрифты)."""
        self._global_qss = qss
        app = QApplication.instance()
        if app is not None and qss is not None:
            app.setStyleSheet(qss)
        elif app is not None and qss is None:
            app.setStyleSheet("")

    def register(
        self,
        widget: QWidget,
        *,
        style_id: str,
        template: Optional[str] = None,
        template_path: Optional[PathLike] = None,
        widget_layer: Optional[Dict[str, Any]] = None,
        component_layer: Optional[Dict[str, Any]] = None,
        apply_now: bool = True,
    ) -> int:
        """
        Зарегистрировать виджет.

        Шаблон: `template` или `template_path`, иначе берётся из `registry.get(style_id)`.
        Токены: merge(bundle.default_tokens, global, widget_layer, component_layer).
        """
        reg_id = self._next_id
        self._next_id += 1

        def _on_destroyed(_ref: weakref.ReferenceType[QWidget]) -> None:
            self._entries = [e for e in self._entries if e.reg_id != reg_id]

        wref = weakref.ref(widget, _on_destroyed)
        entry = _Registration(
            reg_id=reg_id,
            wref=wref,
            style_id=style_id,
            template=template,
            template_path=str(template_path) if template_path is not None else None,
            widget_layer=dict(widget_layer) if widget_layer else {},
            component_layer=dict(component_layer) if component_layer else {},
        )
        self._entries.append(entry)

        if apply_now:
            self._apply_one(entry)

        return reg_id

    def update_registration(
        self,
        reg_id: int,
        *,
        widget_layer: Optional[Dict[str, Any]] = None,
        component_layer: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновить слои для записи и перерисовать виджет."""
        for e in self._entries:
            if e.reg_id == reg_id:
                if widget_layer is not None:
                    e.widget_layer = dict(widget_layer)
                if component_layer is not None:
                    e.component_layer = dict(component_layer)
                self._apply_one(e)
                return True
        return False

    def refresh(self, style_id: Optional[str] = None) -> None:
        """Пересчитать стили: только для `style_id` или для всех зарегистрированных."""
        for e in list(self._entries):
            if style_id is None or e.style_id == style_id:
                self._apply_one(e)

    def remove_registration(self, reg_id: int) -> None:
        """Удалить запись (перед повторной register с тем же виджетом)."""
        self._entries = [e for e in self._entries if e.reg_id != reg_id]

    def _resolve_template_text(self, entry: _Registration) -> str:
        if entry.template is not None:
            return entry.template
        if entry.template_path:
            return resolve_template(template_path=entry.template_path)
        bundle = self._registry.get(entry.style_id)
        if bundle and bundle.template:
            return bundle.template
        return ""

    def _merged_tokens(self, entry: _Registration) -> Dict[str, Any]:
        bundle = self._registry.get(entry.style_id)
        style_defaults = bundle.default_tokens if bundle else {}
        return merge_token_layers(
            style_defaults,
            self._global_tokens,
            entry.widget_layer,
            entry.component_layer,
        )

    def _apply_one(self, entry: _Registration) -> None:
        w = entry.wref()
        if w is None:
            return
        text = self._resolve_template_text(entry)
        if not text.strip():
            w.setStyleSheet(minimal_fallback_qss())
            return
        tokens = self._merged_tokens(entry)
        qss = render_qss(text, tokens)
        w.setStyleSheet(qss)
