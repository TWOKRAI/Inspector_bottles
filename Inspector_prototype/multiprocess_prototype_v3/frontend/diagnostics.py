# multiprocess_prototype_v3/frontend/diagnostics.py
"""
Опциональная телеметрия UI: одна подписка на WidgetSignalBus + шапка.

Включается только при ui_diagnostics.enabled в конфиге GUI (Dict at Boundary).
Не дублирует бизнес-логику — только наблюдение за уже существующими сигналами.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from frontend_module.core.qt_imports import QWidget
from frontend_module.widgets.widget_signal_bus import WidgetSignalBus


def _parse_level(name: str) -> int:
    return getattr(logging, str(name).upper(), logging.INFO)


def _make_handler(
    *,
    log: logging.Logger,
    level: int,
    include_prefixes: Optional[Tuple[str, ...]],
    buffer: Optional[List[Tuple[str, object]]],
    buffer_max: int,
) -> Callable[[str, object], None]:
    def on_event(event_id: str, payload: object) -> None:
        if include_prefixes is not None and not any(
            event_id.startswith(p) for p in include_prefixes
        ):
            return
        if buffer is not None and buffer_max > 0:
            if len(buffer) >= buffer_max:
                buffer.pop(0)
            buffer.append((event_id, payload))
        log.log(level, "ui_event %s %r", event_id, payload)

    return on_event


def _connect_bus(
    bus: WidgetSignalBus,
    slot: Callable[[str, object], None],
    disconnectors: List[Callable[[], None]],
    seen: Set[int],
) -> None:
    bid = id(bus)
    if bid in seen:
        return
    seen.add(bid)
    bus.event_emitted.connect(slot)
    disconnectors.append(lambda b=bus, s=slot: b.event_emitted.disconnect(s))


def attach_ui_diagnostics(main_window: QWidget, config: Dict[str, Any]) -> Optional["UiDiagnosticsSession"]:
    """
    Подписаться на события UI. Вызывать после полной сборки MainWindow.

    config["ui_diagnostics"] — dict:
      - enabled: bool (обязательно True для активации)
      - log_level: str, по умолчанию INFO
      - logger_name: str, по умолчанию multiprocess_prototype.ui
      - include_prefixes: list[str] | None — если задано, только event_id с таким префиксом
      - buffer_max: int — если > 0, последние события хранятся в session.recent_events (отладка/тесты)

    Returns:
        UiDiagnosticsSession или None.
    """
    raw = config.get("ui_diagnostics") or {}
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None

    level = _parse_level(raw.get("log_level", "INFO"))
    log_name = str(raw.get("logger_name") or "multiprocess_prototype_v3.ui")
    log = logging.getLogger(log_name)
    prefixes_raw = raw.get("include_prefixes")
    include_prefixes: Optional[Tuple[str, ...]] = None
    if prefixes_raw is not None:
        include_prefixes = tuple(str(p) for p in prefixes_raw if p)
        if not include_prefixes:
            include_prefixes = None

    buffer_max = int(raw.get("buffer_max") or 0)
    buffer: Optional[List[Tuple[str, object]]] = [] if buffer_max > 0 else None

    on_event = _make_handler(
        log=log,
        level=level,
        include_prefixes=include_prefixes,
        buffer=buffer,
        buffer_max=buffer_max,
    )
    disconnectors: List[Callable[[], None]] = []
    seen: Set[int] = set()

    tab_widget = getattr(main_window, "tab_widget", None)
    if tab_widget is not None:
        bus = getattr(tab_widget, "signal_bus", None)
        if isinstance(bus, WidgetSignalBus):
            _connect_bus(bus, on_event, disconnectors, seen)

        for w in tab_widget.findChildren(QWidget):
            child_bus = getattr(w, "signal_bus", None)
            if isinstance(child_bus, WidgetSignalBus):
                _connect_bus(child_bus, on_event, disconnectors, seen)

    header = getattr(main_window, "_header", None)

    def on_header_action(action_id: str) -> None:
        on_event("header.action_triggered", {"action_id": action_id})

    if header is not None and hasattr(header, "action_triggered"):
        header.action_triggered.connect(on_header_action)
        disconnectors.append(
            lambda h=header, s=on_header_action: h.action_triggered.disconnect(s)
        )

    return UiDiagnosticsSession(
        recent_events=buffer if buffer is not None else [],
        _disconnectors=disconnectors,
    )


class UiDiagnosticsSession:
    """Живёт на время окна; вызовите disconnect() при закрытии (опционально)."""

    def __init__(
        self,
        *,
        recent_events: List[Tuple[str, object]],
        _disconnectors: List[Callable[[], None]],
    ) -> None:
        self._recent_events = recent_events
        self._disconnectors = _disconnectors

    @property
    def recent_events(self) -> List[Tuple[str, object]]:
        return self._recent_events

    def disconnect(self) -> None:
        for fn in self._disconnectors:
            try:
                fn()
            except (TypeError, RuntimeError):
                pass
        self._disconnectors.clear()
