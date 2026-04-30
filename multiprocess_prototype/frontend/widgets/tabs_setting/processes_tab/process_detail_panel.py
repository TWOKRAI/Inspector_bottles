"""ProcessDetailPanel — QStackedWidget с формами деталей процесса и воркера.

Четыре страницы:
  0 — Placeholder (подсказка «выберите элемент»)
  1 — ProcessInfoForm (детали процесса)
  2 — WorkerInfoForm (детали воркера с секцией Timing)
  3 — PluginPage (PluginChainEditor + PluginConfigPanel)
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .plugin_chain_editor import PluginChainEditor
from .plugin_config_panel import PluginConfigPanel

# --- Цвета статусов процессов ---
STATUS_COLORS: dict[str, str] = {
    "running":      "#4CAF50",
    "stopped":      "#9E9E9E",
    "crashed":      "#F44336",
    "failed":       "#F44336",
    "starting":     "#FFC107",
    "stopping":     "#FFC107",
    "configured":   "#2196F3",
}

# --- Цвета статусов воркеров ---
WORKER_STATUS_COLORS: dict[str, str] = {
    "running": "#4CAF50",
    "idle":    "#9E9E9E",
    "stopped": "#9E9E9E",
    "error":   "#F44336",
}

# Fallback-цвет для неизвестных статусов
_DEFAULT_STATUS_COLOR = "#9E9E9E"


def _make_status_label(status: str, color_map: dict[str, str]) -> QLabel:
    """Создать QLabel со статусом и цветным фоном.

    Args:
        status:    Строка статуса.
        color_map: Словарь {статус: hex-цвет}.

    Returns:
        Настроенный QLabel.
    """
    label = QLabel(status)
    color = color_map.get(status, _DEFAULT_STATUS_COLOR)
    # Тёмный текст на светлом фоне — проверяем яркость
    bg = QColor(color)
    brightness = bg.red() * 0.299 + bg.green() * 0.587 + bg.blue() * 0.114
    text_color = "#000000" if brightness > 128 else "#FFFFFF"
    label.setStyleSheet(
        f"background-color: {color}; color: {text_color}; "
        f"padding: 2px 6px; border-radius: 3px;"
    )
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


# ===========================================================================
# ProcessInfoForm — форма деталей процесса (страница 1)
# ===========================================================================

class _ProcessInfoForm(QWidget):
    """Форма с деталями выбранного процесса."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QFormLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # --- Поля формы ---
        self._name_label = QLabel()
        font = QFont()
        font.setBold(True)
        self._name_label.setFont(font)

        self._status_label = QLabel()
        self._pid_label = QLabel()
        self._class_label = QLabel()
        self._priority_label = QLabel()
        self._alive_label = QLabel()
        self._workers_label = QLabel()

        layout.addRow("Имя:", self._name_label)
        layout.addRow("Статус:", self._status_label)
        layout.addRow("PID:", self._pid_label)
        layout.addRow("Класс:", self._class_label)
        layout.addRow("Приоритет:", self._priority_label)
        layout.addRow("Alive:", self._alive_label)
        layout.addRow("Воркеры:", self._workers_label)

    def fill(self, data: dict) -> None:
        """Заполнить форму данными процесса.

        Args:
            data: Словарь с ключами name, status, pid, class_path,
                  priority, alive, workers.
        """
        name = data.get("name", "—")
        status = data.get("status", "unknown")
        pid = data.get("pid")
        class_path = data.get("class_path", "—")
        priority = data.get("priority", "—")
        alive = data.get("alive", False)
        workers: dict = data.get("workers", {})

        self._name_label.setText(name)

        # Цветной лейбл статуса — пересоздаём через stylesheet
        color = STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR)
        bg = QColor(color)
        brightness = bg.red() * 0.299 + bg.green() * 0.587 + bg.blue() * 0.114
        text_color = "#000000" if brightness > 128 else "#FFFFFF"
        self._status_label.setText(status)
        self._status_label.setStyleSheet(
            f"background-color: {color}; color: {text_color}; "
            f"padding: 2px 6px; border-radius: 3px;"
        )

        self._pid_label.setText(str(pid) if pid is not None else "—")
        self._class_label.setText(class_path or "—")
        self._priority_label.setText(str(priority) if priority else "—")
        self._alive_label.setText("Да" if alive else "Нет")

        # Сводка воркеров
        if workers:
            total = len(workers)
            running = sum(
                1 for w in workers.values() if w.get("status") == "running"
            )
            self._workers_label.setText(f"{running} запущено / {total} всего")
        else:
            self._workers_label.setText("—")


# ===========================================================================
# WorkerInfoForm — форма деталей воркера (страница 2)
# ===========================================================================

class _WorkerInfoForm(QWidget):
    """Форма с деталями выбранного воркера.

    Структура:
    - Верхняя часть: QFormLayout с базовыми полями
    - Секция Timing: QGroupBox с целевым интервалом (редактируемый)
      и readonly-метками цикла/частоты/задержки
    - Нижняя часть: QFormLayout с alive/рестарты/ошибка

    Signal:
        target_interval_changed(str, int) — (worker_key, new_value_ms).
        Emitится только при ручном изменении QSpinBox.
    """

    # Сигнал для уведомления об изменении целевого интервала
    target_interval_changed: Signal = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        # --- Верхняя форма: базовые поля воркера ---
        top_form = QFormLayout()
        top_form.setSpacing(8)
        top_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._name_label = QLabel()
        name_font = QFont()
        name_font.setBold(True)
        self._name_label.setFont(name_font)

        self._proc_label = QLabel()
        self._status_label = QLabel()
        self._type_label = QLabel()
        self._protected_label = QLabel("Защищён")

        # Строка Protected — скрывается если protected=False
        self._protected_row_label = QLabel("Защита:")

        top_form.addRow("Имя:", self._name_label)
        top_form.addRow("Процесс:", self._proc_label)
        top_form.addRow("Статус:", self._status_label)
        top_form.addRow("Тип:", self._type_label)
        top_form.addRow(self._protected_row_label, self._protected_label)

        root_layout.addLayout(top_form)

        # --- Секция Timing ---
        timing_box = QGroupBox("Timing")
        timing_layout = QFormLayout(timing_box)
        timing_layout.setSpacing(6)
        timing_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Целевой интервал — редактируемый QSpinBox
        self._interval_spinbox = QSpinBox()
        self._interval_spinbox.setRange(0, 10000)
        self._interval_spinbox.setSuffix(" мс")
        self._interval_spinbox.setToolTip("Целевой интервал цикла воркера (мс)")

        # Readonly-поля мониторинга
        self._cycle_label = QLabel("—")
        self._hz_label = QLabel("—")
        self._sleep_label = QLabel("—")

        timing_layout.addRow("Целевой интервал:", self._interval_spinbox)
        timing_layout.addRow("Цикл:", self._cycle_label)
        timing_layout.addRow("Частота:", self._hz_label)
        timing_layout.addRow("Задержка:", self._sleep_label)

        root_layout.addWidget(timing_box)

        # --- Нижняя форма: alive / рестарты / ошибка ---
        bottom_form = QFormLayout()
        bottom_form.setSpacing(8)
        bottom_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._alive_label = QLabel()
        self._restarts_label = QLabel()
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)

        bottom_form.addRow("Alive:", self._alive_label)
        bottom_form.addRow("Рестарты:", self._restarts_label)
        bottom_form.addRow("Ошибка:", self._error_label)

        root_layout.addLayout(bottom_form)
        root_layout.addStretch()

        # Текущий worker_key — нужен для emit сигнала
        self._current_worker_key: str = ""

        # Подключить сигнал после инициализации
        self._interval_spinbox.valueChanged.connect(self._on_interval_changed)

    # ------------------------------------------------------------------
    # Заполнение данными
    # ------------------------------------------------------------------

    def fill(self, proc_name: str, data: dict) -> None:
        """Заполнить форму данными воркера.

        Блокирует сигнал QSpinBox при программном заполнении.

        Args:
            proc_name: Имя родительского процесса.
            data:      Merged dict с config и monitor полями воркера.
        """
        name = data.get("name", "—")
        self._current_worker_key = f"{proc_name}/{name}"

        self._name_label.setText(name)
        self._proc_label.setText(proc_name)

        # Статус с цветным фоном
        status = data.get("status", "unknown")
        color = WORKER_STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR)
        bg = QColor(color)
        brightness = bg.red() * 0.299 + bg.green() * 0.587 + bg.blue() * 0.114
        text_color = "#000000" if brightness > 128 else "#FFFFFF"
        self._status_label.setText(status)
        self._status_label.setStyleSheet(
            f"background-color: {color}; color: {text_color}; "
            f"padding: 2px 6px; border-radius: 3px;"
        )

        self._type_label.setText(str(data.get("worker_type", "—")))

        # Protected — показать строку только если защищён
        protected = data.get("protected", False)
        self._protected_row_label.setVisible(protected)
        self._protected_label.setVisible(protected)

        # Целевой интервал — программное заполнение без сигнала
        target_ms = data.get("target_interval_ms", 0) or 0
        self._interval_spinbox.blockSignals(True)
        self._interval_spinbox.setValue(int(target_ms))
        self._interval_spinbox.blockSignals(False)

        # Timing (monitor-поля)
        self._fill_timing(data)

        # Нижние поля
        is_alive = data.get("is_alive", False)
        self._alive_label.setText("Да" if is_alive else "Нет")
        self._restarts_label.setText(str(data.get("restart_count", 0)))
        last_error = data.get("last_error") or "—"
        self._error_label.setText(str(last_error))

    def update_timing(self, data: dict) -> None:
        """Обновить только timing-метки без переключения страницы.

        Используется для live-обновления в реальном времени.

        Args:
            data: Словарь с ключами cycle_duration_ms, effective_hz, sleep_ms.
        """
        self._fill_timing(data)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _fill_timing(self, data: dict) -> None:
        """Заполнить readonly-метки секции Timing.

        Args:
            data: Словарь с monitor-полями (cycle_duration_ms, effective_hz, sleep_ms).
        """
        cycle = data.get("cycle_duration_ms")
        hz = data.get("effective_hz")
        sleep = data.get("sleep_ms")

        self._cycle_label.setText(
            f"{cycle:.1f} мс" if cycle is not None else "—"
        )
        self._hz_label.setText(
            f"{hz:.1f} Hz" if hz is not None else "—"
        )
        self._sleep_label.setText(
            f"{sleep:.1f} мс" if sleep is not None else "—"
        )

    def _on_interval_changed(self, value: int) -> None:
        """Обработать ручное изменение QSpinBox целевого интервала.

        Emitит target_interval_changed только если worker_key задан.

        Args:
            value: Новое значение интервала в мс.
        """
        if self._current_worker_key:
            self.target_interval_changed.emit(self._current_worker_key, value)


# ===========================================================================
# _PluginPage — страница с chain editor + config panel (страница 3)
# ===========================================================================

class _PluginPage(QWidget):
    """Страница plugin UI: PluginChainEditor слева, PluginConfigPanel справа.

    QSplitter(Horizontal): chain editor (stretch 2) | config panel (stretch 1).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chain_editor = PluginChainEditor()
        self.config_panel = PluginConfigPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.chain_editor)
        splitter.addWidget(self.config_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)


# ===========================================================================
# ProcessDetailPanel — главный QStackedWidget
# ===========================================================================

class ProcessDetailPanel(QStackedWidget):
    """Панель деталей выбранного элемента дерева процессов.

    Страницы:
      0 — Placeholder (подсказка)
      1 — ProcessInfoForm (детали процесса)
      2 — WorkerInfoForm (детали воркера + Timing)
      3 — PluginPage (PluginChainEditor + PluginConfigPanel)

    Signals:
        target_interval_changed(str, int): (worker_key, new_value_ms).
            Emitится при ручном изменении целевого интервала воркера.
    """

    target_interval_changed: Signal = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # --- Страница 0: Placeholder ---
        self._placeholder = QLabel("Выберите элемент для просмотра деталей")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #9E9E9E;")
        self._placeholder.setWordWrap(True)

        # --- Страница 1: форма процесса ---
        self._process_form = _ProcessInfoForm()

        # --- Страница 2: форма воркера ---
        self._worker_form = _WorkerInfoForm()
        # Пробросить сигнал воркера наружу
        self._worker_form.target_interval_changed.connect(
            self.target_interval_changed
        )

        # --- Страница 3: plugin UI (chain editor + config panel) ---
        self._plugin_page = _PluginPage()

        self.addWidget(self._placeholder)    # index 0
        self.addWidget(self._process_form)   # index 1
        self.addWidget(self._worker_form)    # index 2
        self.addWidget(self._plugin_page)    # index 3

        self.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def chain_editor(self) -> PluginChainEditor:
        """Доступ к PluginChainEditor на странице плагинов."""
        return self._plugin_page.chain_editor

    @property
    def config_panel(self) -> PluginConfigPanel:
        """Доступ к PluginConfigPanel на странице плагинов."""
        return self._plugin_page.config_panel

    def show_placeholder(self) -> None:
        """Показать страницу-заглушку (ничего не выбрано)."""
        self.setCurrentIndex(0)

    def show_process(self, data: dict) -> None:
        """Показать детали процесса (legacy, без плагинов).

        Args:
            data: Словарь с ключами name, status, pid, class_path,
                  priority, alive, workers.
        """
        self._process_form.fill(data)
        self.setCurrentIndex(1)

    def show_plugins(self) -> None:
        """Показать страницу plugin UI (chain editor + config panel)."""
        self.setCurrentIndex(3)

    def show_worker(self, proc_name: str, data: dict) -> None:
        """Показать детали воркера.

        Принимает merged dict с config- и monitor-полями.

        Config-поля:  name, worker_type, protected, target_interval_ms
        Monitor-поля: status, is_alive, restart_count, last_error,
                      cycle_duration_ms, effective_hz, sleep_ms

        Args:
            proc_name: Имя родительского процесса.
            data:      Merged dict со всеми полями воркера.
        """
        self._worker_form.fill(proc_name, data)
        self.setCurrentIndex(2)

    def update_worker_timing(self, data: dict) -> None:
        """Обновить только timing-метки воркера без переключения страницы.

        Используется для live-обновления при активной странице 2.

        Args:
            data: Словарь с ключами cycle_duration_ms, effective_hz, sleep_ms.
        """
        self._worker_form.update_timing(data)


__all__ = ["ProcessDetailPanel"]
