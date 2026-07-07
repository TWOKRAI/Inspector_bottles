# -*- coding: utf-8 -*-
"""ProcessSelectorSection — селекторы процесса/воркера/display инспектора (F.6).

Объединяет три формы карточки ноды:
- «Процесс / Воркер» (+ кнопки Закрепить/Открепить + тумблер bypass) — plugin-режим;
- «IPC-таргет команд» — plugin-режим, опциональная маршрутизация команд;
- «Display» — display-режим.

Секция владеет СВОИМ локальным флагом ``_suppress`` (закрывает Н-6: прежний хрупкий
вложенный ``_suppress_changes = True`` внутри уже-подавленного show_plugin_node с
двумя finally). Populate/configure выполняются под локальным подавлением — панель
больше не оборачивает наполнение combo в собственный suppress.

Секция эмитит «сырые» сигналы выбора (без node_id/from_process) — контекст добавляет
панель-оркестратор при переизлучении в свои внешние сигналы.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ProcessSelectorSection(QWidget):
    """Виджет-контейнер селекторов процесса/воркера/display с локальным suppress."""

    # Signal: (new_process) — выбран IPC-таргет; панель добавит node_id.
    sig_target_selected = Signal(str)
    # Signal: (display_id) — выбран display; панель добавит node_id.
    sig_display_selected = Signal(str)
    # Signal: (from_process, to_process) — перенос узла в другой процесс.
    sig_move_requested = Signal(str, str)
    # Signal: (worker) — выбран воркер; панель персистит assigned_worker.
    sig_worker_selected = Signal(str)
    # Signal: (locked) — кнопки Закрепить/Открепить; панель адресует текущую ноду.
    sig_lock_set = Signal(bool)
    # Signal: (checked) — тумблер bypass; панель шлёт set_enabled в процесс ноды.
    sig_bypass_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suppress: bool = False
        self._current_process: str = ""
        # Провайдеры данных (bound-методы панели, читают live services). По умолчанию — пусто.
        self._process_names_fn: Callable[[], list[str]] = list
        self._workers_fn: Callable[[str], list[str]] = lambda _p: []
        self._display_entries_fn: Callable[[], list[Any]] = list
        self._init_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _init_ui(self) -> None:
        # Секция — прозрачный контейнер: три формы кладём в собственный layout,
        # каждая управляет своей видимостью независимо.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # --- Форма «Процесс / Воркер» + фиксация + bypass (Phase B) ---
        self._move_process_form = QWidget()
        mp_layout = QFormLayout(self._move_process_form)
        mp_layout.setContentsMargins(0, 0, 0, 0)
        mp_layout.setSpacing(4)
        self._move_process_combo = QComboBox()
        self._move_process_combo.setObjectName("MoveProcessCombo")
        self._move_process_combo.setToolTip(
            "Перенести этот узел (его плагины) в другой процесс. Плагины в одном\n"
            "процессе исполняются последовательно; разные процессы — параллельно."
        )
        self._move_worker_combo = QComboBox()
        self._move_worker_combo.setObjectName("MoveWorkerCombo")
        self._move_worker_combo.setToolTip(
            "Воркер процесса, в котором исполняется узел.\nСписок — воркеры выбранного процесса (вкладка «Процессы»)."
        )
        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(6)
        pw_layout.addWidget(self._move_process_combo, 1)
        pw_layout.addWidget(self._move_worker_combo, 1)
        mp_layout.addRow("Процесс / Воркер:", pw_row)

        self._lock_btn = QPushButton("Закрепить")
        self._lock_btn.setObjectName("NodeLockButton")
        self._lock_btn.setMinimumHeight(40)
        self._lock_btn.setToolTip("Зафиксировать ноду: не двигается и пропускается авто-раскладкой")
        self._unlock_btn = QPushButton("Открепить")
        self._unlock_btn.setObjectName("NodeUnlockButton")
        self._unlock_btn.setMinimumHeight(40)
        self._unlock_btn.setToolTip("Снять фиксацию ноды")
        lock_row = QWidget()
        lock_layout = QHBoxLayout(lock_row)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        lock_layout.setSpacing(6)
        lock_layout.addWidget(self._lock_btn, 1)
        lock_layout.addWidget(self._unlock_btn, 1)
        mp_layout.addRow("Фиксация:", lock_row)

        self._bypass_check = QCheckBox("Нода включена (обрабатывает кадр)")
        self._bypass_check.setObjectName("NodeEnabledCheck")
        self._bypass_check.setChecked(True)
        self._bypass_check.setMinimumHeight(32)
        self._bypass_check.setToolTip(
            "Снять галку → нода пропускает кадр без обработки (bypass).\n"
            "Удобно отключить circle_detector, пока настраиваешь hsv-маску."
        )
        mp_layout.addRow("Обработка:", self._bypass_check)
        outer.addWidget(self._move_process_form)
        self._move_process_form.setVisible(False)

        # --- Форма «IPC-таргет команд» ---
        self._target_process_form = QWidget()
        tp_layout = QFormLayout(self._target_process_form)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(4)
        self._target_process_combo = QComboBox()
        self._target_process_combo.setObjectName("TargetProcessCombo")
        self._target_process_combo.setToolTip(
            "Куда слать команды от плагина (IPC-маршрутизация). НЕ меняет процесс,\n"
            "в котором исполняется нода — назначение процесса/воркера будет в Phase B/C."
        )
        tp_layout.addRow("IPC-таргет команд:", self._target_process_combo)
        outer.addWidget(self._target_process_form)
        self._target_process_form.setVisible(False)

        # --- Форма «Display» (display-узлы) ---
        self._display_id_form = QWidget()
        di_layout = QFormLayout(self._display_id_form)
        di_layout.setContentsMargins(0, 0, 0, 0)
        di_layout.setSpacing(4)
        self._display_id_combo = QComboBox()
        self._display_id_combo.setObjectName("DisplayIdCombo")
        di_layout.addRow("Display:", self._display_id_combo)
        outer.addWidget(self._display_id_form)
        self._display_id_form.setVisible(False)

        # Внутренние обработчики (все проверяют локальный _suppress).
        self._target_process_combo.currentIndexChanged.connect(self._on_target_process_combo_changed)
        self._display_id_combo.currentIndexChanged.connect(self._on_display_id_combo_changed)
        self._move_process_combo.currentIndexChanged.connect(self._on_move_process_combo_changed)
        self._move_worker_combo.currentIndexChanged.connect(self._on_move_worker_combo_changed)
        self._lock_btn.clicked.connect(lambda: self._emit_lock(True))
        self._unlock_btn.clicked.connect(lambda: self._emit_lock(False))
        self._bypass_check.toggled.connect(self._on_bypass_toggled)

    def set_providers(
        self,
        process_names_fn: Callable[[], list[str]],
        workers_fn: Callable[[str], list[str]],
        display_entries_fn: Callable[[], list[Any]],
    ) -> None:
        """Задать провайдеры данных (bound-методы панели, читают live services)."""
        self._process_names_fn = process_names_fn
        self._workers_fn = workers_fn
        self._display_entries_fn = display_entries_fn

    # ------------------------------------------------------------------ #
    #  Публичный API: режимы отображения                                  #
    # ------------------------------------------------------------------ #

    def configure_plugin_mode(
        self,
        current_process: str,
        target_process: str,
        available_processes: list[str] | None,
        assigned_worker: str,
    ) -> None:
        """Сконфигурировать селекторы для plugin-ноды (под локальным подавлением).

        Строку «Процесс / Воркер» показываем всегда; форму IPC-таргета — только если
        combo непустой (иначе пустой disabled combo путает пользователя).
        """
        self._current_process = current_process
        self._suppress = True
        try:
            # Сброс тумблера bypass в «включено» (readback живого состояния пока нет).
            self._bypass_check.setChecked(True)
            self._display_id_form.setVisible(False)

            self._populate_target_process_combo(target_process)
            has_targets = bool(self._target_process_combo.isEnabled())
            self._target_process_form.setVisible(has_targets)

            self._populate_move_process_combo(available_processes)
            self._populate_move_worker_combo(current_process, assigned_worker)
            self._move_process_form.setVisible(True)
        finally:
            self._suppress = False

    def configure_display_mode(self, display_id: str) -> None:
        """Сконфигурировать селекторы для display-ноды (под локальным подавлением)."""
        self._suppress = True
        try:
            self._target_process_form.setVisible(False)
            self._move_process_form.setVisible(False)
            self._display_id_form.setVisible(True)
            self._populate_display_id_combo(display_id)
        finally:
            self._suppress = False

    def clear(self) -> None:
        """Скрыть все формы селекторов (нет выбора)."""
        self._target_process_form.setVisible(False)
        self._move_process_form.setVisible(False)
        self._display_id_form.setVisible(False)

    def current_display_id(self) -> str:
        """Текущий выбранный display_id (для refresh)."""
        idx = self._display_id_combo.currentIndex()
        if idx >= 0:
            return self._display_id_combo.itemData(idx) or ""
        return ""

    def refresh_display(self, current_id: str) -> None:
        """Перезаполнить combo «Display» (под локальным подавлением)."""
        self._suppress = True
        try:
            self._populate_display_id_combo(current_id)
        finally:
            self._suppress = False

    # ------------------------------------------------------------------ #
    #  Заполнение combo                                                    #
    # ------------------------------------------------------------------ #

    def _populate_target_process_combo(self, current_value: str = "") -> None:
        """Заполнить combo «IPC-таргет» именами процессов из рецепта (пусто → disabled)."""
        combo = self._target_process_combo
        combo.clear()
        process_names = self._process_names_fn()
        if not process_names:
            combo.setEnabled(False)
            return
        combo.setEnabled(True)
        for name in process_names:
            combo.addItem(name)
        if current_value:
            idx = combo.findText(current_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _populate_display_id_combo(self, current_display_id: str = "") -> None:
        """Заполнить combo «Display» из DisplayCatalog (пусто → disabled)."""
        combo = self._display_id_combo
        combo.clear()
        entries = self._display_entries_fn()
        if not entries:
            combo.setEnabled(False)
            return
        combo.setEnabled(True)
        for entry in entries:
            label = f"{entry.name} ({entry.id})" if entry.name else entry.id
            combo.addItem(label, userData=entry.id)
        if current_display_id:
            for i in range(combo.count()):
                if combo.itemData(i) == current_display_id:
                    combo.setCurrentIndex(i)
                    break

    def _populate_move_process_combo(self, available_processes: list[str] | None) -> None:
        """Заполнить combo «Перенести в процесс» (плейсхолдер первым, userData='')."""
        combo = self._move_process_combo
        combo.clear()
        combo.addItem("— перенести в… —", userData="")
        for name in available_processes or []:
            combo.addItem(name, userData=name)
        combo.setCurrentIndex(0)

    def _populate_move_worker_combo(self, process_name: str, current_worker: str = "") -> None:
        """Заполнить воркер-combo воркерами процесса (пусто/нет процесса → message_processor)."""
        combo = self._move_worker_combo
        combo.clear()
        workers = self._workers_fn(process_name)
        combo.setEnabled(bool(workers))
        for name in workers:
            combo.addItem(name, userData=name)
        if current_worker:
            idx = combo.findData(current_worker)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------ #
    #  Внутренние обработчики (все проверяют локальный _suppress)          #
    # ------------------------------------------------------------------ #

    def _on_target_process_combo_changed(self, index: int) -> None:
        if self._suppress:
            return
        new_process = self._target_process_combo.currentText()
        if new_process:
            self.sig_target_selected.emit(new_process)

    def _on_display_id_combo_changed(self, index: int) -> None:
        if self._suppress:
            return
        new_display_id = self._display_id_combo.itemData(index) or ""
        if new_display_id:
            self.sig_display_selected.emit(new_display_id)

    def _on_move_process_combo_changed(self, index: int) -> None:
        """Выбор процесса-приёмника → перезаполнить воркер-combo + эмит переноса.

        D.1: эмитим from_process = current_process (presenter ждёт from_process).
        Воркер-combo всегда отражает воркеры релевантного процесса (выбранного или текущего).
        """
        if self._suppress:
            return
        to_process = self._move_process_combo.itemData(index) or ""
        # Перезаполнение под локальным подавлением (Н-6: раньше был вложенный suppress панели).
        self._suppress = True
        try:
            self._populate_move_worker_combo(to_process or self._current_process)
        finally:
            self._suppress = False
        if to_process and self._current_process and to_process != self._current_process:
            self.sig_move_requested.emit(self._current_process, to_process)

    def _on_move_worker_combo_changed(self, index: int) -> None:
        """Выбор воркера → persist assigned_worker (панель шлёт field_changed)."""
        if self._suppress:
            return
        worker = self._move_worker_combo.itemData(index) or ""
        if worker and self._current_process:
            self.sig_worker_selected.emit(worker)

    def _on_bypass_toggled(self, checked: bool) -> None:
        if self._suppress:
            return
        self.sig_bypass_toggled.emit(bool(checked))

    def _emit_lock(self, locked: bool) -> None:
        if self._suppress:
            return
        self.sig_lock_set.emit(locked)
