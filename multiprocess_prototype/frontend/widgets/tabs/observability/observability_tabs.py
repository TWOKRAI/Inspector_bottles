# -*- coding: utf-8 -*-
"""
ObservabilityTabs — вкладка «Наблюдаемость» в трёхколоночном виде (Ф5.19).

Три раздела Логи / Ошибки / Статистика показаны как остальные вкладки приложения
(``BaseTreeNavTab``): колонка 1 — кнопки раздела (Обновить/Копировать/Очистить),
колонка 2 — список разделов, колонка 3 — таблица записей. Раньше это был
``QTabWidget`` с вкладками сверху; переведено на общий tree-nav паттерн (как
Settings) для единообразия UI.

Каждый раздел — инстанс ОДНОГО ``RecordHistoryPanel`` на свой kind (log/error/stats).
Целая история — из общего стора (Ф5.20a), живой хвост — из hub→GUI-канала (Ф5.20b):
подключается через ``bind_live_source`` к сигналу
``DataReceiverBridge.observability_received`` и раздаётся всем панелям (панель не
своего kind вернёт 0). Панели строятся сразу (секции нелейзи), поэтому живой хвост
доходит и до неактивных разделов.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseTreeNavTab,
    SectionSpec,
)
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .record_history_panel import RecordHistoryPanel
from .record_source import RecordSource, open_default_source

_TABS = [
    ("log", "Логи"),
    ("error", "Ошибки"),
    ("stats", "Статистика"),
]


def _layout_factory() -> DiffScrollTabLayout:
    return DiffScrollTabLayout(title="Наблюдаемость", action_width=160, nav_width=200)


class _PanelSection:
    """Адаптер ``RecordHistoryPanel`` → ``SectionProtocol``.

    Отдаёт панель как content-виджет и её кнопки в action-колонку (колонка 1).
    ``on_activated/on_deactivated`` — no-op: живой хвост течёт независимо от того,
    какой раздел открыт.
    """

    def __init__(self, key: str, title: str, panel: RecordHistoryPanel) -> None:
        self._key = key
        self._title = title
        self._panel = panel

    @property
    def key(self) -> str:
        """Уникальный идентификатор раздела (== kind)."""
        return self._key

    @property
    def title(self) -> str:
        """Отображаемое название раздела."""
        return self._title

    def widget(self) -> QWidget:
        """Корневой QWidget раздела — панель истории."""
        return self._panel

    def action_buttons(self) -> List[QWidget]:
        """Кнопки раздела для action-колонки (Обновить/Копировать/Очистить)."""
        return self._panel.action_buttons()

    def on_activated(self) -> None:
        """Переключение на раздел — действий не требует (хвост течёт всегда)."""

    def on_deactivated(self) -> None:
        """Уход с раздела — действий не требует."""


class ObservabilityTabs(BaseTreeNavTab):
    """Вкладка «Наблюдаемость»: 3 раздела Логи/Ошибки/Статистика через BaseTreeNavTab."""

    def __init__(self, source: Optional[RecordSource] = None, parent: QWidget | None = None) -> None:
        # source=None → открыть общий стор по умолчанию (в тестах передаётся fake).
        # Владеем стором ТОЛЬКО когда открыли его сами → только его и закрываем
        # (переданный извне закрывает владелец) — 5.21 (e).
        self._owns_source = source is None
        self._source = source if source is not None else open_default_source()

        # Панели строим ДО super().__init__: фабрики секций (вызываются внутри
        # super) возвращают адаптеры над готовыми панелями, а живой хвост доходит
        # до всех трёх сразу (секции нелейзи → создаются в __init__ базы).
        self._panels: Dict[str, RecordHistoryPanel] = {
            kind: RecordHistoryPanel(self._source, kind, title=title) for kind, title in _TABS
        }

        super().__init__(
            title="Наблюдаемость",
            sections=self._build_sections(),
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            parent=parent,
        )
        self.populate()

        # Стор держит WAL-reader на observability.db — освобождаем на выходе из
        # приложения (вкладка живёт весь сеанс, closeEvent у child не приходит).
        self._wire_close_on_quit()

    def _tree_object_name(self) -> str:
        return "ObservabilityTreeNav"

    def _build_sections(self) -> "list[SectionSpec[Any]]":
        """Собрать SectionSpec по одному на kind — фабрика возвращает адаптер над панелью."""
        return [
            SectionSpec(
                key=kind,
                title=title,
                factory=(lambda _ctx, k=kind, t=title: _PanelSection(k, t, self._panels[k])),
            )
            for kind, title in _TABS
        ]

    # ------------------------------------------------------------------
    # Стор / teardown
    # ------------------------------------------------------------------

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
        """Слот сигнала DataReceiverBridge.observability_received: раздать записи панелям.

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

    @classmethod
    def create(cls, services: Any, runtime: Any) -> "ObservabilityTabs":
        """Фабрика вкладки (Tab.create-контракт): стор по умолчанию + живой хвост из bridge."""
        tabs = cls()
        bridge = getattr(runtime, "data_bridge", None)
        if bridge is not None:
            tabs.bind_live_source(bridge)
        return tabs
