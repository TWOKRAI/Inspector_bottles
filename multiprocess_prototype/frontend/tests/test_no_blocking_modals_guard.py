# -*- coding: utf-8 -*-
"""Страж модальных окон умеет краснеть (корневой ``conftest.py``).

Молчащий страж ничего не доказывает: пока он не показан красным, «модалок в
прогоне нет» и «страж не работает» выглядят одинаково — оба дают зелёный
прогон. Здесь он показан красным на каждом классе вызова, который стережёт.

Проверяется и то, ради чего он сделан BaseException'ом: прод-код вокруг GUI
щедр на ``except Exception``, и страж, пойманный такой веткой, вернул бы тишину.
"""

from __future__ import annotations

import pytest

from conftest import BlockingModalInTest


def test_a_modal_message_box_fails_instead_of_waiting(qapp):
    from PySide6.QtWidgets import QMessageBox

    with pytest.raises(BlockingModalInTest, match="QMessageBox.warning"):
        QMessageBox.warning(None, "заголовок", "текст")


def test_dialog_exec_is_guarded_too(qapp):
    """``exec`` у произвольного QDialog — та же остановка прогона, что и у QMessageBox."""
    from PySide6.QtWidgets import QDialog

    dialog = QDialog()
    with pytest.raises(BlockingModalInTest, match="QDialog.exec"):
        dialog.exec()


def test_file_dialog_is_guarded_too(qapp):
    from PySide6.QtWidgets import QFileDialog

    with pytest.raises(BlockingModalInTest, match="QFileDialog.getOpenFileName"):
        QFileDialog.getOpenFileName(None, "выберите файл")


def test_the_guard_survives_an_except_exception_around_the_gui_call(qapp):
    """Прод-код ловит ``Exception`` вокруг GUI — страж обязан пройти сквозь такую ветку."""
    from PySide6.QtWidgets import QMessageBox

    caught_by_production_style_handler = False
    try:
        try:
            QMessageBox.critical(None, "заголовок", "текст")
        except Exception:  # noqa: BLE001 — ровно так пишет прод-код вокруг GUI
            caught_by_production_style_handler = True
    except BlockingModalInTest:
        pass

    assert caught_by_production_style_handler is False, "страж пойман `except Exception` и снова стал тишиной"


def test_a_test_may_override_the_guard_when_the_dialog_is_the_subject(qapp, monkeypatch):
    """Свою подмену тест ставит ПОСЛЕ стража — и она выигрывает."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: "показано"))

    assert QMessageBox.warning(None, "заголовок", "текст") == "показано"
