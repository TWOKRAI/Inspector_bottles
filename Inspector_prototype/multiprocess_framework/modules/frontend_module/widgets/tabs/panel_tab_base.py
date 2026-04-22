# -*- coding: utf-8 -*-
"""
PanelTabBase — универсальная tab-обёртка: RegisterBindingContext -> placeholder или panel widget.

Подкласс задаёт атрибуты класса:
    _panel_class   — тип панели (BaseWidget-наследник)
    _config_class  — тип Pydantic-схемы UiConfig
    _placeholder_name — текст для заглушки при отсутствии RegistersManager

Для дополнительных kwargs панели -- переопределить _build_panel_kwargs() -> dict.
"""
from __future__ import annotations

from typing import Any, Generic, Optional, Type, TypeVar, Union

from frontend_module.core.qt_imports import QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config

from .binding_context import RegisterBindingContext
from .placeholder_utils import create_registers_placeholder
from .tab_widget import BaseTab

try:
    from ..keyboard.touch_keyboard_bind import merge_touch_keyboard_dicts
except ImportError:

    def merge_touch_keyboard_dicts(*parts: Any) -> Any:
        """Fallback: склейка dict-частей touch_keyboard конфига."""
        out: dict[str, Any] = {}
        for p in parts:
            if isinstance(p, dict):
                out = {**out, **p}
        return out if out else None


# TypeVar для панели и конфига — подкласс фиксирует конкретные типы
TPanel = TypeVar("TPanel", bound=QWidget)
TConfig = TypeVar("TConfig")


class PanelTabBase(BaseTab, Generic[TPanel, TConfig]):
    """
    Универсальная tab-обёртка: RegisterBindingContext -> placeholder или panel widget.

    Подкласс задаёт атрибуты класса::

        class MyTab(PanelTabBase[MyPanel, MyConfig]):
            _panel_class = MyPanel
            _config_class = MyConfig
            _placeholder_name = "Моя вкладка"

    Для дополнительных kwargs панели -- переопределить ``_build_panel_kwargs()``.
    """

    # --- Атрибуты класса, задаются подклассом ---
    _panel_class: Type[TPanel]
    _config_class: Type[TConfig]
    _placeholder_name: str = "Вкладка"

    def __init__(
        self,
        *,
        registers_manager: Any = None,
        ui: Optional[Union[Any, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[QWidget] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._u = coerce_schema_config(ui, self._config_class)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._u, "touch_keyboard", None)
        )
        self._panel: Optional[TPanel] = None
        self._extra_kwargs = kwargs
        self._init_ui()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def registers_manager(self) -> Any:
        """RegistersManager, переданный при создании (или None)."""
        return self._registers_manager

    @property
    def panel(self) -> Optional[TPanel]:
        """Панель (BaseWidget-наследник) или None, если rm отсутствует."""
        return self._panel

    # ------------------------------------------------------------------
    # Хуки для подклассов
    # ------------------------------------------------------------------

    def _build_panel_kwargs(self) -> dict[str, Any]:
        """
        Дополнительные kwargs для конструктора панели.

        Переопределить в подклассе, если панель принимает аргументы
        помимо registers_manager / ui / touch_keyboard / parent.
        Базовая реализация возвращает пустой dict.
        """
        return {}

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Вертикальный layout: placeholder или панель на всю высоту."""
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder(self._placeholder_name))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        extra = self._build_panel_kwargs()
        self._panel = self._panel_class(
            registers_manager=rm,
            ui=self._u,
            touch_keyboard=self._touch_keyboard,
            parent=self,
            **extra,
        )
        layout.addWidget(self._panel, 1)
