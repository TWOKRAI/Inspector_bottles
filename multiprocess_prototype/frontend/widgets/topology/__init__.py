"""Topology package — presenter для load/save SystemBlueprint (YAML).

Визуальный редактор (TopologyEditorWidget + дети) удалён как мёртвый код
(K8, Ф4-добор H7): 0 прод-потребителей. Живым остаётся только TopologyPresenter,
который использует pipeline/presenter.py для load/save рецептов.
"""
from .presenter import TopologyPresenter

__all__ = ["TopologyPresenter"]
