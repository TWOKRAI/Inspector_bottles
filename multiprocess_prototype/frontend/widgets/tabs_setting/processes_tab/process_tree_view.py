"""ProcessTreeView — дерево процессов/воркеров, основанное на EntityTreeWidget.

Наследует EntityTreeWidget и переопределяет _populate() для merge-логики
из двух источников данных:
- ProcessEditorModel  — конфигурация (class_path, priority, protected, worker_type)
- ProcessMonitorModel — runtime статус (alive, pid, status, workers, timing)

Визуальные различия:
- Процесс только в editor (не запущен) — italic, синий цвет, статус "configured"
- Процесс только в monitor (нет в editor) — обычный + "(external)" в имени
- Процесс в обоих — bold + runtime статус
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QStandardItem

from multiprocess_prototype.frontend.widgets.base.editor.entity_tree_widget import (
    ROLE_CHILD,
    ROLE_PARAM,
    ROLE_PARENT,
    ROLE_TYPE,
    EntityTreeWidget,
)

from .constants import (
    PROC_CONFIG_PARAMS,
    PROC_RUNTIME_PARAMS,
    STATUS_COLORS,
    STATUS_ICONS,
    WORKER_CONFIG_PARAMS,
    WORKER_RUNTIME_PARAMS,
    WORKER_STATUS_COLORS,
)
from .process_monitor_model import ProcessMonitorModel
from .process_tree_config import PROCESS_TREE_CONFIG

logger = logging.getLogger(__name__)

# Цвет для процессов, присутствующих только в editor (не запущены)
_COLOR_EDITOR_ONLY = "#2196F3"
# Серый цвет для параметров и групп
_COLOR_GRAY = QColor(140, 140, 140)


class ProcessTreeView(EntityTreeWidget):
    """Дерево процессов: процессы -> параметры + воркеры -> параметры.

    Корневые узлы — процессы (bold, с цветовым статусом).
    Дочерние: группа параметров процесса + воркеры, у каждого — группа параметров.

    Поддерживает merged view из ProcessEditorModel и ProcessMonitorModel.
    Если editor_model=None — работает как раньше (только monitor, backward-compatible).
    """

    def __init__(
        self,
        model: ProcessMonitorModel,
        *,
        editor_model=None,
        parent=None,
    ) -> None:
        """Инициализировать дерево.

        Args:
            model:        Модель данных мониторинга процессов (обязательная).
            editor_model: Модель конфигурации (ProcessEditorModel). Если None —
                          дерево работает только с monitor-данными (backward-compatible).
            parent:       Родительский виджет.
        """
        super().__init__(PROCESS_TREE_CONFIG, parent=parent)
        self._monitor_model = model

        # editor_model хранится без type annotation для избежания circular import
        self._editor_model = editor_model

    # ------------------------------------------------------------------
    # Переопределение _populate для merge-логики
    # ------------------------------------------------------------------

    def _populate(self, root: QStandardItem) -> None:
        """Заполнить дерево строками из merged данных обеих моделей.

        Строит иерархию: Процесс -> Параметры + Воркеры -> Параметры воркера.
        При editor_model=None работает только с monitor-данными (backward-compatible).

        Args:
            root: Невидимый корневой элемент модели (invisibleRootItem).
        """
        monitor_processes = self._monitor_model.processes

        # Если editor_model не задан — backward-compatible режим (только monitor)
        if self._editor_model is None:
            self._populate_from_sources(root, {}, monitor_processes)
            return

        # --- Merged режим ---
        editor_processes = self._editor_model.processes
        self._populate_from_sources(root, editor_processes, monitor_processes)

    def _populate_from_sources(
        self,
        root: QStandardItem,
        editor_processes: dict,
        monitor_processes: dict,
    ) -> None:
        """Заполнить дерево из двух источников (editor + monitor).

        Args:
            root:              Корневой элемент модели.
            editor_processes:  Словарь процессов из editor (может быть пустым).
            monitor_processes: Словарь процессов из monitor.
        """
        # Union ключей из обеих моделей
        all_proc_keys = set(editor_processes.keys()) | set(monitor_processes.keys())

        if not all_proc_keys:
            placeholder = QStandardItem("Нет данных о процессах")
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            root.appendRow([placeholder])
            return

        # Сортируем: сначала по sort_order из editor, потом alphabetically
        def _sort_key(k: str) -> tuple:
            ed = editor_processes.get(k, {})
            return (ed.get("sort_order", 9999), k)

        for proc_key in sorted(all_proc_keys, key=_sort_key):
            ed_data = editor_processes.get(proc_key)
            mon_data = monitor_processes.get(proc_key)

            # --- Merged dict для параметров процесса ---
            merged_proc = self._merge_proc_data(proc_key, ed_data, mon_data)

            # Строка процесса (кастомная — с визуальными стилями по состоянию)
            proc_row = self._make_process_row(proc_key, ed_data, mon_data, merged_proc)
            root.appendRow(proc_row)

            proc_item = proc_row[0]

            # Группа параметров процесса
            proc_params_group = self._make_group_item(
                "Параметры", "proc_param_group", proc_key
            )
            proc_item.appendRow(self._make_full_row(proc_params_group))
            self._build_param_rows(
                proc_params_group, proc_key, merged_proc,
                self._config.parent_level.params, "proc_param",
            )

            # Воркеры процесса
            self._populate_workers(proc_item, proc_key, ed_data, mon_data)

    # ------------------------------------------------------------------
    # Merge данных процесса
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_proc_data(
        proc_key: str,
        ed_data: dict | None,
        mon_data: dict | None,
    ) -> dict:
        """Объединить данные editor и monitor в один dict для параметров.

        Config-параметры (class_path, priority, auto_start) — из editor.
        Runtime-параметры (pid, alive) — из monitor.

        Args:
            proc_key: Ключ процесса (для логирования).
            ed_data:  Данные из editor или None.
            mon_data: Данные из monitor или None.

        Returns:
            Объединённый dict параметров.
        """
        merged: dict[str, Any] = {}

        # Config-параметры: приоритет у editor, fallback на monitor
        for pkey in PROC_CONFIG_PARAMS:
            if ed_data is not None and pkey in ed_data:
                merged[pkey] = ed_data[pkey]
            elif mon_data is not None and pkey in mon_data:
                merged[pkey] = mon_data[pkey]

        # Runtime-параметры: из monitor
        for pkey in PROC_RUNTIME_PARAMS:
            if mon_data is not None and pkey in mon_data:
                merged[pkey] = mon_data[pkey]

        return merged

    # ------------------------------------------------------------------
    # Воркеры
    # ------------------------------------------------------------------

    def _populate_workers(
        self,
        proc_item: QStandardItem,
        proc_key: str,
        ed_data: dict | None,
        mon_data: dict | None,
    ) -> None:
        """Добавить строки воркеров как дочерние узлы процесса.

        Args:
            proc_item: QStandardItem строки процесса (COL_NAME).
            proc_key:  Ключ процесса.
            ed_data:   Данные процесса из editor или None.
            mon_data:  Данные процесса из monitor или None.
        """
        # Воркеры из editor: {worker_name: worker_dict}
        ed_workers: dict[str, dict] = {}
        if self._editor_model is not None and ed_data is not None:
            for _wk, wd in self._editor_model.workers_for_process(proc_key).items():
                wname = wd.get("name", _wk)
                ed_workers[wname] = wd

        # Воркеры из monitor: {worker_name: worker_dict}
        mon_workers: dict[str, dict] = {}
        if mon_data is not None:
            raw_workers = mon_data.get("workers", {})
            if isinstance(raw_workers, dict):
                mon_workers = raw_workers

        # Union имён воркеров
        all_worker_names = set(ed_workers.keys()) | set(mon_workers.keys())
        if not all_worker_names:
            return

        # Сортируем по sort_order из editor, потом alphabetically
        def _worker_sort_key(wname: str) -> tuple:
            ew = ed_workers.get(wname, {})
            return (ew.get("sort_order", 9999), wname)

        for wname in sorted(all_worker_names, key=_worker_sort_key):
            ew = ed_workers.get(wname)
            mw = mon_workers.get(wname)

            # Merge данных воркера
            merged_worker = self._merge_worker_data(ew, mw)

            # Строка воркера (кастомная — с protected-меткой и статусом)
            worker_row = self._make_worker_row(proc_key, wname, ew, mw, merged_worker)
            proc_item.appendRow(worker_row)

            worker_item = worker_row[0]

            # Группа параметров воркера
            worker_params_group = self._make_group_item(
                "Параметры", "worker_param_group", proc_key, wname
            )
            worker_item.appendRow(self._make_full_row(worker_params_group))
            self._build_param_rows(
                worker_params_group, proc_key, merged_worker,
                self._config.child_level.params, "worker_param",
                child_key=wname,
            )

    @staticmethod
    def _merge_worker_data(
        ew: dict | None,
        mw: dict | None,
    ) -> dict:
        """Объединить данные editor и monitor в один dict для параметров воркера.

        Args:
            ew: Данные воркера из editor или None.
            mw: Данные воркера из monitor или None.

        Returns:
            Объединённый dict параметров.
        """
        merged: dict[str, Any] = {}

        # Config-параметры
        for pkey in WORKER_CONFIG_PARAMS:
            if ew is not None and pkey in ew:
                merged[pkey] = ew[pkey]
            elif mw is not None and pkey in mw:
                merged[pkey] = mw[pkey]

        # Runtime-параметры
        for pkey in WORKER_RUNTIME_PARAMS:
            if mw is not None and pkey in mw:
                merged[pkey] = mw[pkey]

        return merged

    # ------------------------------------------------------------------
    # Построители строк (кастомные — с визуальными стилями)
    # ------------------------------------------------------------------

    def _make_process_row(
        self,
        proc_key: str,
        ed_data: dict | None,
        mon_data: dict | None,
        merged_data: dict,
    ) -> list[QStandardItem]:
        """Создать строку-заголовок процесса (bold, с иконкой статуса).

        Логика визуальных стилей:
        - Только в editor -> italic, синий цвет, статус "configured"
        - Только в monitor -> обычный шрифт, имя + "(external)"
        - В обоих -> bold + runtime статус из monitor

        Args:
            proc_key:    Ключ процесса.
            ed_data:     Данные из ProcessEditorModel или None.
            mon_data:    Данные из ProcessMonitorModel или None.
            merged_data: Объединённые данные для summary.

        Returns:
            Список из 4 QStandardItem.
        """
        only_editor = ed_data is not None and mon_data is None
        only_monitor = ed_data is None and mon_data is not None
        in_both = ed_data is not None and mon_data is not None

        # Определяем статус и иконку
        if only_editor:
            status_text = "configured"
            status_color = _COLOR_EDITOR_ONLY
        else:
            status_text = mon_data.get("status", "stopped")
            status_color = STATUS_COLORS.get(status_text, "#95a5a6")

        status_icon = STATUS_ICONS.get(status_text, "\u25cb")

        # Отображаемое имя
        if only_monitor:
            display_name = f"■ {proc_key} (external) ({status_text} {status_icon})"
        else:
            display_name = f"■ {proc_key} ({status_text} {status_icon})"

        # Сводка из конфига
        summary = ""
        sb = self._config.parent_level.summary_builder
        if sb is not None:
            try:
                summary = sb(merged_data)
            except Exception:
                summary = ""

        # --- COL_NAME ---
        name_item = QStandardItem(display_name)
        font = QFont()
        if only_editor:
            font.setItalic(True)
            name_item.setForeground(QBrush(QColor(_COLOR_EDITOR_ONLY)))
        elif in_both:
            font.setBold(True)
        name_item.setFont(font)
        name_item.setData(proc_key, Qt.ItemDataRole.UserRole)
        # Используем "process" вместо "parent" для backward-compatible с widget.py
        name_item.setData("process", ROLE_TYPE)
        name_item.setData(proc_key, ROLE_PARENT)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_VAL: статус ---
        val_item = QStandardItem(status_text)
        val_item.setForeground(QBrush(QColor(status_color)))
        val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_COMMENT: класс (короткое имя) ---
        class_path = merged_data.get("class_path", "")
        class_short = class_path.rsplit(".", 1)[-1] if class_path else "—"
        comment_item = QStandardItem(class_short)
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_SUMMARY ---
        summary_item = QStandardItem(summary)
        summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        return [name_item, val_item, comment_item, summary_item]

    def _make_worker_row(
        self,
        proc_key: str,
        wname: str,
        ew: dict | None,
        mw: dict | None,
        merged_data: dict,
    ) -> list[QStandardItem]:
        """Создать строку-заголовок воркера.

        Args:
            proc_key:    Ключ родительского процесса.
            wname:       Имя воркера.
            ew:          Данные из editor или None.
            mw:          Данные из monitor или None.
            merged_data: Объединённые данные для summary.

        Returns:
            Список из 4 QStandardItem.
        """
        # Определяем protected из editor
        is_protected = bool(ew.get("protected", False)) if ew else False
        protected_mark = " [P]" if is_protected else ""

        # Статус и иконка
        if mw is not None:
            status = mw.get("status", "unknown")
        elif ew is not None:
            status = "configured"
        else:
            status = "unknown"

        status_icon = STATUS_ICONS.get(status, "\u25cb")
        display_name = f"□ {wname}{protected_mark} ({status} {status_icon})"

        # Сводка из конфига
        summary = ""
        sb = self._config.child_level.summary_builder
        if sb is not None:
            try:
                summary = sb(merged_data)
            except Exception:
                summary = ""

        # --- COL_NAME ---
        name_item = QStandardItem(display_name)
        # Используем "worker" вместо "child" для backward-compatible с widget.py
        name_item.setData("worker", ROLE_TYPE)
        name_item.setData(proc_key, ROLE_PARENT)
        name_item.setData(wname, ROLE_CHILD)
        name_item.setData(f"{proc_key}/{wname}", Qt.ItemDataRole.UserRole)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_VAL: статус ---
        color_hex = WORKER_STATUS_COLORS.get(status, "#95a5a6")
        if status == "configured":
            color_hex = _COLOR_EDITOR_ONLY
        val_item = QStandardItem(status)
        val_item.setForeground(QBrush(QColor(color_hex)))
        val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_COMMENT: тип воркера ---
        worker_type = merged_data.get("worker_type", "—") or "—"
        comment_item = QStandardItem(str(worker_type))
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # --- COL_SUMMARY: timing ---
        summary_item = QStandardItem(summary)
        summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        return [name_item, val_item, comment_item, summary_item]


__all__ = ["ProcessTreeView"]
