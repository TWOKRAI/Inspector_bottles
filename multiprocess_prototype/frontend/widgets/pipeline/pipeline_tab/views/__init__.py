"""Views-подпакет: табличный вид, переключатель видов, layout-константы.

Реэкспорты Qt-виджетов не выполняются на уровне __init__ — они ленивые,
чтобы pure-Python модули (auto_layout) могли импортировать _layout_constants
без PySide6 в окружении.
"""

__all__ = [
    "PipelineTableView",
    "PipelineViewSwitch",
]
