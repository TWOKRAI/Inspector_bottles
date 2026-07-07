# -*- coding: utf-8 -*-
"""ExecInfoSection — блок «Исполнение» инспектора (F.6, разрез god-файла).

Read-only (Phase A): показывает, в каком ПРОЦЕССЕ исполняется нода и в каком ВОРКЕРЕ
каждый плагин (+ порядок в цепочке). Воркеры назначаются автоматически в GenericProcess
(source → свой source_producer_<plugin>; processing → общий pipeline_executor,
последовательно), поэтому блок read-only — назначение придёт в Phase C.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from .selectors_data import worker_label


class ExecInfoSection(QWidget):
    """Секция «Исполнение»: процесс + воркер/порядок по плагинам."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

    def populate(self, process_name: str, node_category: str, plugins: list | None) -> None:
        """Заполнить блок: процесс + воркер/порядок по плагинам.

        Шаг считается только среди processing-плагинов (источники независимы, свой поток).
        """
        self.clear()

        proc_value = QLabel(process_name)
        proc_value.setProperty("role", "exec-process")
        self._layout.addRow("Процесс:", proc_value)

        plugin_list = plugins or []
        processing_total = sum(
            1 for p in plugin_list if ((p.get("category") if isinstance(p, dict) else "") or node_category) != "source"
        )
        step = 0
        for p in plugin_list:
            if isinstance(p, dict):
                pname = p.get("plugin_name", "")
                pcat = p.get("category") or node_category
            else:
                pname = str(p)
                pcat = node_category
            if pcat != "source":
                step += 1
                worker = worker_label(pcat, pname, step, processing_total)
            else:
                worker = worker_label("source", pname, 0, 0)
            self._layout.addRow(f"{pname}:", QLabel(worker))

    def clear(self) -> None:
        """Очистить строки блока «Исполнение»."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
