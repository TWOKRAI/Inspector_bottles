# -*- coding: utf-8 -*-
"""unsaved_changes.py — общий диалог «несохранённые правки графа» (RS-4 #6).

confirm_unsaved_changes — единый трёхкнопочный диалог (Сохранить / Не сохранять /
Отмена — стандартная конвенция Save / Don't Save / Cancel). Используется ВСЕМИ точками, где опасное действие может
выбросить несохранённые правки редактора топологии:
  - активация другого рецепта (RecipesTab.confirm_discard_changes);
  - закрытие приложения (MainWindow.closeEvent);
  - перезапуск UI из Settings→Interface (app.py _request_ui_restart, через
    MainWindow.confirm_discard_topology_changes).

Единый диалог — чтобы формулировки и порядок кнопок не разъезжались между точками
(требование владельца: «Сохранить» — кнопка по умолчанию, безопасный исход).
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QMessageBox, QWidget

UnsavedChoice = Literal["save", "discard", "cancel"]


def confirm_unsaved_changes(
    parent: QWidget | None,
    *,
    allow_save: bool = True,
    text: str = "В редакторе топологии есть несохранённые правки.",
) -> UnsavedChoice:
    """Показать диалог подтверждения при несохранённых правках графа.

    Args:
        parent: родитель модального окна.
        allow_save: показывать ли кнопку «Сохранить». True → она default
            (безопасный исход, правки не теряются). False → save недоступно
            (нечем сохранить), default — «Отмена».
        text: основной текст диалога.

    Returns:
        "save" — сохранить и продолжить; "discard" — продолжить без сохранения;
        "cancel" — отменить действие.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Несохранённые правки графа")
    box.setText(text)

    # Подписи — стандартная конвенция Save / Don't Save / Cancel (требование владельца).
    save_btn = box.addButton("Сохранить", QMessageBox.ButtonRole.AcceptRole) if allow_save else None
    discard_btn = box.addButton("Не сохранять", QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    # «Сохранить» — default (правки не теряются случайно). Без него — «Отмена».
    box.setDefaultButton(save_btn if save_btn is not None else cancel_btn)

    box.exec()
    clicked = box.clickedButton()
    if save_btn is not None and clicked is save_btn:
        return "save"
    if clicked is discard_btn:
        return "discard"
    return "cancel"


__all__ = ["confirm_unsaved_changes", "UnsavedChoice"]
