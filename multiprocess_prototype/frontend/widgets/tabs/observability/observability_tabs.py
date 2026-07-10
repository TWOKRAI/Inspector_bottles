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
        # Владеем стором ТОЛЬКО когда открыли его сами → только его и закрываем
        # (переданный извне закрывает владелец) — 5.21 (e).
        self._owns_source = source is None
        self._source = source if source is not None else open_default_source()
        self._panels: Dict[str, RecordHistoryPanel] = {}
        for kind, title in _TABS:
            panel = RecordHistoryPanel(self._source, kind, title=title)
            self._panels[kind] = panel
            self.addTab(panel, title)
        # Стор держит WAL-reader на observability.db — освобождаем на выходе из
        # приложения (вкладка живёт весь сеанс, closeEvent у child не приходит).
        self._wire_close_on_quit()

    def _wire_close_on_quit(self) -> None:
        """Закрыть собственный стор по QApplication.aboutToQuit (leak WAL-reader; 5.21 (e))."""
        if not self._owns_source or self._source is None:
            return
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.close_source)
        except Exception:  # noqa: BLE001 — отсутствие app не должно ронять конструктор
            pass

    def close_source(self) -> None:
        """Закрыть стор, если владеем им (teardown/тесты). Идемпотентно."""
        if self._owns_source and self._source is not None:
            close = getattr(self._source, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
        self._source = None

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
        # 5.21 (c): бэкенд штампует process в каждую запись; на всякий случай
        # добираем из конверта сообщения (data.process) для записей без поля.
        envelope_process = msg_dict.get("process", "") if isinstance(msg_dict, dict) else ""
        if envelope_process:
            for rec in records:
                if isinstance(rec, dict) and not rec.get("process"):
                    rec["process"] = envelope_process
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
