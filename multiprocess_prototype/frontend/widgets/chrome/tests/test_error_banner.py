"""Тесты ErrorBannerWidget."""
from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.chrome.error_banner import (
    ErrorBannerWidget,
    _MAX_MESSAGES,
)


@pytest.fixture
def banner(qtbot):
    """Создать ErrorBannerWidget, зарегистрировать в qtbot."""
    w = ErrorBannerWidget()
    qtbot.addWidget(w)
    return w


# ---------------------------------------------------------------------------
# Тест 1 — начальное состояние
# ---------------------------------------------------------------------------

def test_initially_hidden(banner: ErrorBannerWidget) -> None:
    """Баннер должен быть скрыт при создании (без сообщений)."""
    assert not banner.isVisible()
    assert len(banner._rows) == 0


# ---------------------------------------------------------------------------
# Тест 2 — show_error делает баннер видимым
# ---------------------------------------------------------------------------

def test_show_error_makes_visible(banner: ErrorBannerWidget) -> None:
    """show_error → баннер становится видимым, строка добавлена."""
    banner.show_error("Ошибка подключения камеры")

    assert banner.isVisible()
    assert len(banner._rows) == 1

    # Проверяем, что текст ошибки присутствует в дочерних виджетах
    from PySide6.QtWidgets import QLabel
    labels = banner._rows[0].findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any("Ошибка подключения камеры" in t for t in texts)


# ---------------------------------------------------------------------------
# Тест 3 — show_warning использует жёлтый стиль
# ---------------------------------------------------------------------------

def test_show_warning(banner: ErrorBannerWidget) -> None:
    """show_warning → баннер видим, строка со стилем предупреждения."""
    banner.show_warning("Низкое освещение")

    assert banner.isVisible()
    assert len(banner._rows) == 1

    # Проверяем стиль строки содержит жёлтый цвет
    row_style = banner._rows[0].styleSheet()
    assert "#eab308" in row_style


# ---------------------------------------------------------------------------
# Тест 4 — dismiss убирает конкретную строку
# ---------------------------------------------------------------------------

def test_dismiss(banner: ErrorBannerWidget) -> None:
    """dismiss(0) должен убрать первую (единственную) строку."""
    banner.show_error("Сообщение 1")
    banner.show_error("Сообщение 2")

    assert len(banner._rows) == 2

    # Сохраняем текст второй строки для проверки после dismiss
    from PySide6.QtWidgets import QLabel
    second_row_labels = banner._rows[1].findChildren(QLabel)
    second_texts = {lbl.text() for lbl in second_row_labels}

    banner.dismiss(0)

    assert len(banner._rows) == 1
    # Баннер всё ещё видим (остался 1 элемент)
    assert banner.isVisible()

    # Оставшаяся строка — это бывшая вторая строка
    remaining_labels = banner._rows[0].findChildren(QLabel)
    remaining_texts = {lbl.text() for lbl in remaining_labels}
    assert second_texts & remaining_texts  # пересечение непустое


# ---------------------------------------------------------------------------
# Тест 5 — FIFO при переполнении
# ---------------------------------------------------------------------------

def test_overflow_fifo(banner: ErrorBannerWidget) -> None:
    """При добавлении 4-го сообщения старейшее (1-е) удаляется."""
    for i in range(_MAX_MESSAGES + 1):
        banner.show_error(f"Ошибка #{i}")

    # Количество строк не превышает максимум
    assert len(banner._rows) == _MAX_MESSAGES

    # Первое сообщение ("Ошибка #0") должно быть удалено,
    # последние 3 должны присутствовать
    from PySide6.QtWidgets import QLabel
    all_texts: set[str] = set()
    for row in banner._rows:
        for lbl in row.findChildren(QLabel):
            all_texts.add(lbl.text())

    # "Ошибка #0" должна отсутствовать (вытеснена FIFO)
    assert "Ошибка #0" not in all_texts
    # "Ошибка #3" (последняя) должна присутствовать
    assert "Ошибка #3" in all_texts


# ---------------------------------------------------------------------------
# Тест 6 — clear() убирает все сообщения и скрывает баннер
# ---------------------------------------------------------------------------

def test_clear(banner: ErrorBannerWidget) -> None:
    """clear() должен убрать все строки и скрыть баннер."""
    banner.show_error("Ошибка 1")
    banner.show_warning("Предупреждение 1")
    assert banner.isVisible()

    banner.clear()

    assert not banner.isVisible()
    assert len(banner._rows) == 0


# ---------------------------------------------------------------------------
# Тест 7 — смешанные ошибки и предупреждения
# ---------------------------------------------------------------------------

def test_mixed_errors_warnings(banner: ErrorBannerWidget) -> None:
    """show_error + show_warning → обе строки присутствуют с разными стилями."""
    banner.show_error("Ошибка: нет сигнала")
    banner.show_warning("Предупреждение: низкий FPS")

    assert len(banner._rows) == 2
    assert banner.isVisible()

    error_style = banner._rows[0].styleSheet()
    warning_style = banner._rows[1].styleSheet()

    # Ошибка — красный цвет
    assert "#dc2626" in error_style
    # Предупреждение — жёлтый цвет
    assert "#eab308" in warning_style
