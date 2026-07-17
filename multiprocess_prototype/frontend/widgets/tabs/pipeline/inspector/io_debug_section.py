"""IoDebugSection — сворачиваемая панель «I/O (debug)» внизу карточки ноды (Этап 5).

Показывает O(1)-сводку входа/выхода выбранного плагина, которую бэкенд публикует в
реактивное дерево по пути ``processes.{proc}.plugins.{plugin}.io_peek`` (IoPeekPublisher,
throttle 1 Гц). Generic — работает для ЛЮБОГО плагина (line_filter, modbus, рендер…),
поля не зашиты.

Подписка узкая: один fan-out на ``processes.*.plugins.*.io_peek``, callback фильтрует
по активному пути (текущая нода). Это не glob ``processes.*`` — мимо проходят только
io_peek-дельты, callback дёшев.

«Заморозить» — чисто UI: переключатель замораживает отображение (последний снимок
остаётся на экране), бэкенд продолжает публиковать. Повторное нажатие возобновляет.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Стиль окон вход/выход: моноширинный шрифт покрупнее и светлее (по запросу владельца);
# рамка для визуального разделения двух окон.
_IO_TEXT_STYLE = (
    "font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
    "color: #f5f8fa; background: #1b1b1b; border: 1px solid #3a3a3a; padding: 6px;"
)

# Один fan-out паттерн на все плагины; callback фильтрует по активному пути.
_IO_PEEK_PATTERN = "processes.*.plugins.*.io_peek"


def _default_render(value: dict) -> tuple[str, str, str]:
    """Рендер io_peek плагина: {method, input:{count,items}, output:{count}}."""
    method = value.get("method", "")
    method_ru = {"process": "обработка", "produce": "генерация"}.get(method, method or "—")
    in_data = value.get("input", {}) or {}
    out_data = value.get("output", {}) or {}
    out_count = out_data.get("count", 0)
    is_source = in_data.get("items") is None
    if is_source:
        status = f"{method_ru} · выход: {out_count}"
    else:
        status = f"{method_ru} · вход: {in_data.get('count', 0)} · выход: {out_count}"
    try:
        in_text = "— (источник: нет входа)" if is_source else json.dumps(in_data, indent=2, ensure_ascii=False)
        out_text = json.dumps(out_data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        in_text, out_text = str(in_data), str(out_data)
    return status, in_text, out_text


class IoDebugSection(QWidget):
    """Сворачиваемая секция I/O-отладки одного плагина.

    Использование:
        section = IoDebugSection(bindings)   # bindings = GuiStateBindings | None
        section.set_target("draw", "overlay_draw")  # при выборе ноды
        section.clear_target()                       # при снятии выбора
    """

    def __init__(
        self,
        bindings: Any = None,
        parent: QWidget | None = None,
        *,
        peek_pattern: str = _IO_PEEK_PATTERN,
        render_fn: Any = None,
        title: str = "I/O (debug)",
    ) -> None:
        super().__init__(parent)
        self._bindings: Any = None
        self._subscribed: bool = False
        # Паттерн fan-out + рендер настраиваются: плагин (по умолчанию) или
        # устройство (devices.state.*.io_peek + raw TX/RX рендер).
        self._peek_pattern: str = peek_pattern
        self._render_fn = render_fn or _default_render
        self._title = title
        # Активный путь io_peek (точное совпадение фильтрует чужие дельты). Пусто → секция спит.
        self._active_path: str = ""
        self._frozen: bool = False
        self._body_visible: bool = False
        self._init_ui()
        if bindings is not None:
            self.set_bindings(bindings)

    def set_bindings(self, bindings: Any) -> None:
        """Передать GuiStateBindings (приходит из set_services позже __init__).

        Идемпотентно: подписка fan-out на io_peek вешается ОДИН раз.
        """
        self._bindings = bindings
        if bindings is None or self._subscribed:
            return
        # Узкая подписка: один fan-out на io_peek (callback фильтрует по пути).
        try:
            bindings.bind_fanout(self._peek_pattern, self._on_io_peek, owner=self)
            self._subscribed = True
        except Exception:
            pass  # bindings без bind_fanout (legacy) → секция статична, не падаем

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        # Заголовок-переключатель сворачивания (стартует свёрнутым — не захламляет карту).
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self._toggle_btn = QPushButton(f"▸ {self._title}")
        self._toggle_btn.setObjectName("IoDebugToggle")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setToolTip("Показать сводку входных/выходных данных плагина")
        self._toggle_btn.clicked.connect(self._on_toggle)
        header_layout.addWidget(self._toggle_btn, 1)

        self._freeze_btn = QPushButton("Заморозить")
        self._freeze_btn.setObjectName("IoDebugFreeze")
        self._freeze_btn.setCheckable(True)
        self._freeze_btn.setToolTip("Заморозить отображение, чтобы прочитать снимок (бэкенд не трогается)")
        self._freeze_btn.clicked.connect(self._on_freeze)
        header_layout.addWidget(self._freeze_btn)
        layout.addWidget(header_row)

        # Тело: статус + ДВА отдельных окна (вход и выход), бок о бок.
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(2)
        self._status = QLabel("нет данных")
        self._status.setObjectName("IoDebugStatus")
        body_layout.addWidget(self._status)

        windows_row = QWidget()
        windows_layout = QHBoxLayout(windows_row)
        windows_layout.setContentsMargins(0, 0, 0, 0)
        windows_layout.setSpacing(6)
        self._input_text = self._make_window(windows_layout, "Вход", "IoDebugInput")
        self._output_text = self._make_window(windows_layout, "Выход", "IoDebugOutput")
        body_layout.addWidget(windows_row)
        layout.addWidget(self._body)
        self._body.setVisible(False)

    def _make_window(self, parent_layout: QHBoxLayout, caption: str, obj_name: str) -> QLabel:
        """Создать колонку «подпись + авто-растущий текст» и вернуть текстовый QLabel.

        QLabel (а не QPlainTextEdit) — раскрывается под контент целиком, без
        вложенного скролла: вертикальный overflow обрабатывает мастер-скролл
        (как параметры плагина). Текст моноширинный, выделяемый мышью (копирование).
        """
        col = QWidget()
        col_layout = QVBoxLayout(col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(2)
        label = QLabel(caption)
        label.setObjectName(f"{obj_name}Label")
        col_layout.addWidget(label)
        text = QLabel("")
        text.setObjectName(obj_name)
        text.setStyleSheet(_IO_TEXT_STYLE)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        text.setFrameShape(QFrame.Shape.NoFrame)
        col_layout.addWidget(text)
        # AlignTop: колонки выравниваются по верхней кромке (одинаковая высота задаётся
        # в _equalize_heights → оба окна равного размера независимо от объёма контента).
        parent_layout.addWidget(col, 1, Qt.AlignmentFlag.AlignTop)
        return text

    def _equalize_heights(self) -> None:
        """Сделать оба окна одинаковой высоты = высота большего контента.

        QLabel авто-растёт под текст → у входа/выхода разный объём. Берём максимум
        sizeHint и фиксируем обоим минимум → одинаковый размер, верхнее выравнивание,
        без вложенного скролла (overflow обрабатывает мастер-скролл).
        """
        h = max(self._input_text.sizeHint().height(), self._output_text.sizeHint().height())
        self._input_text.setMinimumHeight(h)
        self._output_text.setMinimumHeight(h)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def set_target(self, process_name: str, plugin_name: str) -> None:
        """Привязать секцию к io_peek конкретного плагина (вызывается при выборе ноды)."""
        self.set_active_path(f"processes.{process_name}.plugins.{plugin_name}.io_peek")

    def set_active_path(self, path: str) -> None:
        """Привязать секцию к произвольному пути io_peek (напр. devices.state.<id>.io_peek)."""
        self._active_path = path
        # Сброс на старте: разморозить + почистить (новые данные придут со следующей дельтой).
        self._frozen = False
        self._freeze_btn.setChecked(False)
        self._freeze_btn.setText("Заморозить")
        self._status.setText("ожидание данных…")
        self._reset_windows()
        # Реплей закэшированного значения, если оно уже есть (нода открыта после дельты).
        self._replay_cached()

    def clear_target(self) -> None:
        """Снять привязку (нет выбранной плагин-ноды) — секция спит."""
        self._active_path = ""
        self._status.setText("нет данных")
        self._reset_windows()

    def _reset_windows(self) -> None:
        """Очистить текст и сбросить зафиксированную высоту (новый плагин — свой размер)."""
        self._input_text.setText("")
        self._output_text.setText("")
        self._input_text.setMinimumHeight(0)
        self._output_text.setMinimumHeight(0)

    # ------------------------------------------------------------------ #
    #  Подписка / рендер                                                   #
    # ------------------------------------------------------------------ #

    def _on_io_peek(self, path: str, value: Any) -> None:
        """Fan-out callback: только дельты активного плагина, только если не заморожено."""
        if not self._active_path or path != self._active_path:
            return
        if self._frozen:
            return
        self._render(value)

    def _replay_cached(self) -> None:
        """Подтянуть последнее известное значение io_peek из read-model (если доступно)."""
        if self._bindings is None or not self._active_path:
            return
        read_model = getattr(self._bindings, "read_model", None)
        if read_model is None:
            return
        try:
            value = read_model.get(self._active_path)
        except Exception:
            return
        if value is not None:
            self._render(value)

    def _render(self, value: Any) -> None:
        """Отрисовать снимок io_peek (dict) через настроенную render-стратегию.

        Сырой monotonic-ts не показываем — «живость» видна по меняющемуся
        содержимому окон.
        """
        if not isinstance(value, dict):
            return
        try:
            status, in_text, out_text = self._render_fn(value)
        except Exception:
            return
        self._status.setText(status)
        self._input_text.setText(in_text)
        self._output_text.setText(out_text)
        self._equalize_heights()

    # ------------------------------------------------------------------ #
    #  Обработчики кнопок                                                  #
    # ------------------------------------------------------------------ #

    def _on_toggle(self, checked: bool) -> None:
        self._body_visible = checked
        self._body.setVisible(checked)
        self._toggle_btn.setText(f"▾ {self._title}" if checked else f"▸ {self._title}")

    def _on_freeze(self, checked: bool) -> None:
        self._frozen = checked
        self._freeze_btn.setText("Возобновить" if checked else "Заморозить")
