# -*- coding: utf-8 -*-
"""
WindowConfig — схема описания окна для декларативной сборки.

Список виджетов + layout-подсказки. Используется LayoutComposer (будущий).
"""
from typing import Annotated, Any, Dict, List, Optional

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase


class WindowConfig(SchemaBase):
    """
    Описание окна для сборки из виджетов.

    Позволяет задать layout через конфиг (YAML/JSON).
    """

    window_id: Annotated[
        str,
        FieldMeta("Идентификатор окна", info="main, loading, settings, ..."),
    ] = "main"

    title: Annotated[
        Optional[str],
        FieldMeta("Заголовок окна"),
    ] = None

    width: Annotated[
        int,
        FieldMeta("Ширина", min=100, max=4096),
    ] = 1280

    height: Annotated[
        int,
        FieldMeta("Высота", min=100, max=2160),
    ] = 720

    widgets: Annotated[
        List[Dict[str, Any]],
        FieldMeta("Список виджетов", info="Каждый элемент — WidgetDescriptor или dict"),
    ] = []

    layout: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Параметры layout", info="orientation, spacing, margins"),
    ] = None

    def get_widget_descriptors(self) -> List[Dict[str, Any]]:
        """Список дескрипторов виджетов."""
        return list(self.widgets)
