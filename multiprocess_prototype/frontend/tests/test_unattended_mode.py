# -*- coding: utf-8 -*-
"""Режим без присмотра: модалка не ждёт клика, а получает ответ или закрывается.

Живой стенд с настоящими окнами упирался ровно в это: при закрытии приложение
спрашивает «сохранить несохранённые правки графа?» и стоит до клика. Здесь режим
показан с ОБЕИХ сторон — что он делает включённым и что без него прогон встал бы.

Оригинальный ``QDialog.exec`` снимается на импорте модуля НАМЕРЕННО: autouse-фикстура
корневого ``conftest.py`` подменяет блокирующие вызовы Qt на отказ, и сторож,
проверяемый против подменённого ``exec``, доказывал бы фикстуру, а не себя.
"""

from __future__ import annotations

import gc
import importlib

import pytest
from PySide6.QtWidgets import QDialog

from conftest import BlockingModalInTest
from multiprocess_prototype.frontend import unattended
from multiprocess_prototype.frontend.widgets.dialogs import confirm_unsaved_changes

_REAL_DIALOG_EXEC = QDialog.exec


@pytest.fixture
def mode_on(monkeypatch):
    """Включить режим и обнулить журнал автоответов на время теста."""
    monkeypatch.setattr(unattended, "_UNATTENDED", True)
    monkeypatch.setattr(unattended, "_answers", [])
    monkeypatch.setattr(unattended, "_log", None)
    return unattended


# ==============================================================================
# Ручка
# ==============================================================================


class TestTheKnob:
    def test_off_without_the_env_var(self, monkeypatch) -> None:
        """Без переменной режим выключен — умолчание не включает себя само."""
        monkeypatch.delenv(unattended.ENV_UNATTENDED, raising=False)
        importlib.reload(unattended)
        try:
            assert unattended.is_unattended() is False
        finally:
            monkeypatch.delenv(unattended.ENV_UNATTENDED, raising=False)
            importlib.reload(unattended)

    def test_on_only_for_the_exact_value(self, monkeypatch) -> None:
        """Включает ровно ``1``: «true» — не значение ручки, а надежда на него."""
        monkeypatch.setenv(unattended.ENV_UNATTENDED, "1")
        importlib.reload(unattended)
        assert unattended.is_unattended() is True

        monkeypatch.setenv(unattended.ENV_UNATTENDED, "true")
        importlib.reload(unattended)
        assert unattended.is_unattended() is False

        monkeypatch.delenv(unattended.ENV_UNATTENDED, raising=False)
        importlib.reload(unattended)

    def test_the_value_is_a_snapshot_not_a_live_read(self, monkeypatch) -> None:
        """Запись в окружение ПОСЛЕ импорта режим не меняет.

        Иначе ручка читала бы собственную запись, и режим переключался бы посреди
        прогона — у стенда это значит «часть окон отвечена, часть ждёт клика».
        """
        monkeypatch.delenv(unattended.ENV_UNATTENDED, raising=False)
        importlib.reload(unattended)
        monkeypatch.setenv(unattended.ENV_UNATTENDED, "1")
        assert unattended.is_unattended() is False


# ==============================================================================
# Ярус 1 — названный вопрос отвечается до показа окна
# ==============================================================================


class TestTheNamedQuestion:
    def test_without_the_mode_the_dialog_would_block(self, qapp) -> None:
        """Контроль: без режима этот вызов встал бы до клика оператора.

        Это и есть причина, по которой стенд поднимался headless. Тест держит
        утверждение живым: если диалог когда-нибудь перестанет быть блокирующим,
        красным станет он, а не приёмка стенда через полгода.
        """
        assert unattended.is_unattended() is False
        with pytest.raises(BlockingModalInTest, match="QMessageBox.exec"):
            confirm_unsaved_changes(None, text="есть правки")

    def test_returns_discard_without_touching_the_dialog(self, mode_on, qapp) -> None:
        """С режимом — ответ «не сохранять», и окно не создаётся вовсе.

        Отсутствие ``BlockingModalInTest`` здесь и есть доказательство: страж
        корневого conftest'а сработал бы на любом обращении к ``exec``.
        """
        assert confirm_unsaved_changes(None, text="есть правки") == "discard"

    def test_the_answer_is_discard_even_when_saving_is_possible(self, mode_on, qapp) -> None:
        """``allow_save=True`` не соблазняет режим сохранять.

        Автоматический прогон, пишущий рецепт, портит рабочее дерево владельца:
        GUI-save переписывает yaml без комментариев.
        """
        assert confirm_unsaved_changes(None, allow_save=True, text="есть правки") == "discard"

    def test_the_answer_is_recorded_with_its_question(self, mode_on, qapp) -> None:
        """Автоответ виден: пара «вопрос → ответ» ложится в журнал режима."""
        confirm_unsaved_changes(None, text="правки в редакторе топологии")
        answers = unattended.auto_answers()
        assert len(answers) == 1
        question, answer = answers[0]
        assert "правки в редакторе топологии" in question
        assert answer == "discard"

    def test_the_answer_is_spoken_into_the_process_log(self, mode_on, qapp) -> None:
        """Автоответ говорится вслух — молчаливый режим объяснить нечем."""
        said: list[tuple[str, dict]] = []
        unattended.set_logger(lambda message, **kw: said.append((message, kw)))

        confirm_unsaved_changes(None, text="правки")

        assert len(said) == 1
        message, kwargs = said[0]
        assert "unattended.auto_answer" in message
        assert "discard" in message
        assert kwargs.get("module") == "gui"


# ==============================================================================
# Ярус 2 — сторож закрывает всё остальное
# ==============================================================================


class TestTheWatchdog:
    def test_not_installed_when_the_mode_is_off(self, qapp) -> None:
        """Выключенный режим не ставит таймер — цена ровно ноль."""
        assert unattended.install_modal_watchdog(qapp) is None

    def test_closes_a_modal_instead_of_waiting(self, mode_on, qapp) -> None:
        """Модалка, которую никто не назвал, закрывается сторожем, а не ждёт.

        Подстраховка обязательна: без неё сломанный сторож не покраснел бы, а
        подвесил бы сьюту на вложенном цикле событий — это хуже отсутствия теста.
        """
        from PySide6.QtCore import QTimer

        unattended.install_modal_watchdog(qapp, interval_ms=20)

        dialog = QDialog()
        dialog.setWindowTitle("незваная модалка")

        backstop_fired: list[str] = []

        def _backstop() -> None:
            backstop_fired.append("сторож не сработал за 3 с")
            dialog.reject()

        QTimer.singleShot(3000, _backstop)

        _REAL_DIALOG_EXEC(dialog)

        assert backstop_fired == [], backstop_fired[0]
        closed = [pair for pair in unattended.auto_answers() if pair[1] == "closed-by-watchdog"]
        assert len(closed) == 1
        assert "незваная модалка" in closed[0][0]
        assert "QDialog" in closed[0][0]

    def test_the_timer_survives_garbage_collection(self, mode_on, qapp) -> None:
        """Владелец таймера — ``app``, а не возвращённая ссылка.

        Таймер без родителя пережил бы только ближайшую сборку мусора, и сторож умер
        бы молча — прогон встал бы на первой же модалке, а причина выглядела бы как
        «режим не работает», хотя ветка кода исполнялась.
        """
        from PySide6.QtCore import QTimer

        unattended.install_modal_watchdog(qapp, interval_ms=20)
        gc.collect()

        dialog = QDialog()
        dialog.setWindowTitle("после сборки мусора")
        backstop_fired: list[str] = []
        QTimer.singleShot(3000, lambda: (backstop_fired.append("таймер умер"), dialog.reject()))

        _REAL_DIALOG_EXEC(dialog)

        assert backstop_fired == [], backstop_fired[0]
        assert any("после сборки мусора" in q for q, _ in unattended.auto_answers())
