"""test_preview_window.py -- Unit-тесты PreviewWindow (pytest-qt).

Покрытие:
1. Конструктор без router_manager
2. show → label содержит "Ожидание кадров..."
3. close → unsubscribe без исключений (mock router)
4. subscribe(None) → не падает, статус "не активна"
5. _numpy_to_qimage BGR → QImage не null
6. open_for_display → возвращает экземпляр PreviewWindow

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.8
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from multiprocess_framework.modules.display_module import DisplayEntry
from multiprocess_prototype.frontend.widgets.displays.preview_window import (
    PreviewWindow,
    open_for_display,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_entry(display_id: str = "main") -> DisplayEntry:
    """Создать DisplayEntry-заглушку."""
    return DisplayEntry(
        id=display_id,
        name=f"Дисплей {display_id}",
        width=640,
        height=480,
        format="BGR",
        fps_limit=30.0,
        ring_buffer_blocks=3,
    )


# ---------------------------------------------------------------------------
# Тест 1: Конструктор без router_manager
# ---------------------------------------------------------------------------


def test_construct_without_router(qtbot):
    """PreviewWindow(entry) конструируется без router_manager — без исключений."""
    entry = _make_entry("main")
    pw = PreviewWindow(entry)
    qtbot.addWidget(pw)
    assert pw is not None
    assert pw._entry.id == "main"


# ---------------------------------------------------------------------------
# Тест 2: show → label содержит "Ожидание кадров..."
# ---------------------------------------------------------------------------


def test_show_displays_placeholder(qtbot):
    """После show() label содержит 'Ожидание кадров...'."""
    entry = _make_entry("main")
    pw = PreviewWindow(entry)
    qtbot.addWidget(pw)
    pw.show()

    label_text = pw._label.text()
    assert "Ожидание кадров" in label_text


# ---------------------------------------------------------------------------
# Тест 3: close → unsubscribe без исключений (mock router)
# ---------------------------------------------------------------------------


def test_close_unsubscribes(qtbot):
    """close() → unsubscribe отработал без исключений (через MagicMock router)."""
    entry = _make_entry("main")
    mock_router = MagicMock()
    mock_router.register_broadcast_route = MagicMock()

    pw = PreviewWindow(entry, router_manager=mock_router)
    qtbot.addWidget(pw)

    # Подписываемся вручную
    pw.subscribe(mock_router)
    assert pw._subscribed is True

    # close() вызывает closeEvent → unsubscribe
    pw.close()
    assert pw._subscribed is False


# ---------------------------------------------------------------------------
# Тест 4: subscribe(None) → не падает, статус "не активна"
# ---------------------------------------------------------------------------


def test_subscribe_with_none_graceful(qtbot):
    """subscribe(None) не падает + статус содержит 'не активна'."""
    entry = _make_entry("main")
    pw = PreviewWindow(entry)
    qtbot.addWidget(pw)

    # Не должно упасть
    pw.subscribe(None)
    status_text = pw._status_label.text()
    assert "не активна" in status_text.lower() or "нет router" in status_text.lower()


# ---------------------------------------------------------------------------
# Тест 5: _numpy_to_qimage BGR → QImage не null
# ---------------------------------------------------------------------------


def test_numpy_to_qimage_bgr(qtbot):
    """np.zeros((480, 640, 3)) + format 'BGR' → QImage не null."""
    arr = np.zeros((480, 640, 3), dtype=np.uint8)
    qimg = PreviewWindow._numpy_to_qimage(arr, "BGR")
    assert qimg is not None
    assert not qimg.isNull()
    assert qimg.width() == 640
    assert qimg.height() == 480


# ---------------------------------------------------------------------------
# Тест 6: open_for_display → возвращает экземпляр, окно создано
# ---------------------------------------------------------------------------


def test_open_for_display(qtbot):
    """open_for_display(entry, None) → возвращает PreviewWindow, окно создано."""
    entry = _make_entry("main")
    pw = open_for_display(entry, router_manager=None)
    qtbot.addWidget(pw)

    assert isinstance(pw, PreviewWindow)
    assert pw._entry.id == "main"

    # Закрываем окно в конце теста
    pw.close()
