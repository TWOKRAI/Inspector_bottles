# -*- coding: utf-8 -*-
"""
ObservabilityTabs — контейнер трёх вкладок наблюдаемости (Ф5.19).

Логи / Ошибки / Статистика — три инстанса ОДНОГО RecordHistoryPanel, каждый на
свой kind (log/error/stats). Целая история — из общего стора (Ф5.20a), живой
хвост — из hub→GUI-канала (Ф5.20b): подключается через ``bind_live_source`` к
сигналу DataReceiverBridge.observability_received и раздаёт записи вкладкам.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QTabWidget, QWidget

from .record_history_panel import RecordHistoryPanel
from .record_source import RecordSource, open_default_source

_TABS = [
    ("log", "Логи"),
    ("error", "Ошибки"),
    ("stats", "Статистика"),
]


class ObservabilityTabs(QTabWidget):
    """Три вкладки Логи/Ошибки/Статистика на одном переиспользуемом виджете."""

    def __init__(self, source: Optional[RecordSource] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # source=None → открыть общий стор по умолчанию (в тестах передаётся fake).
        self._source = source if source is not None else open_default_source()
        self._panels: Dict[str, RecordHistoryPanel] = {}
        for kind, title in _TABS:
            panel = RecordHistoryPanel(self._source, kind, title=title)
            self._panels[kind] = panel
            self.addTab(panel, title)

    def panel(self, kind: str) -> Optional[RecordHistoryPanel]:
        """Панель по kind (для тестов/интеграции)."""
        return self._panels.get(kind)

    # ------------------------------------------------------------------
    # Живой хвост (Ф5.20b)
    # ------------------------------------------------------------------

    def on_observability_records(self, msg_dict: Dict[str, Any]) -> None:
        """Слот сигнала DataReceiverBridge.observability_received: раздать записи вкладкам.

        Каждая панель сама фильтрует по своему kind (matches_live), поэтому просто
        отдаём весь список всем — панель не своего kind вернёт 0.
        """
        records: List[Dict[str, Any]] = msg_dict.get("records", []) if isinstance(msg_dict, dict) else []
        if not records:
            return
        for panel in self._panels.values():
            panel.append_live_records(records)

    def bind_live_source(self, bridge: Any) -> None:
        """Подключить живой хвост к DataReceiverBridge.observability_received."""
        try:
            bridge.observability_received.connect(self.on_observability_records)
        except Exception:  # noqa: BLE001 — отсутствие сигнала не должно ронять GUI
            pass

    @staticmethod
    def create(services: Any, runtime: Any) -> "ObservabilityTabs":
        """Фабрика вкладки (Tab.create-контракт): стор по умолчанию + живой хвост из bridge."""
        tabs = ObservabilityTabs()
        bridge = getattr(runtime, "data_bridge", None)
        if bridge is not None:
            tabs.bind_live_source(bridge)
        return tabs
