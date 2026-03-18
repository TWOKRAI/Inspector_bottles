# multiprocess_prototype\tests\test_renderer_commands.py
"""
Тест RendererProcess: команды set_draw_contours, set_show_original, set_show_mask.

Проверяет, что обработчики команд обновляют состояние.
"""

import pytest


def test_renderer_command_handlers():
    """Renderer обрабатывает set_draw_contours, set_show_original, set_show_mask."""
    from multiprocess_prototype.backend.processes import RendererProcess

    class MockSR:
        memory_manager = None
        get_process_state = lambda *a, **k: {}
        update_process_state = lambda *a, **k: None

    proc = RendererProcess("renderer", shared_resources=MockSR(), config={})
    # Инициализация без воркеров (только команды)
    proc._draw_contours = True
    proc._show_original = True
    proc._show_mask = True
    proc._log_info = lambda *a, **k: None

    r1 = proc._cmd_set_draw_contours({"draw_contours": False})
    assert r1["draw_contours"] is False
    assert proc._draw_contours is False

    r2 = proc._cmd_set_show_original({"show_original": False})
    assert r2["show_original"] is False
    assert proc._show_original is False

    r3 = proc._cmd_set_show_mask({"show_mask": False})
    assert r3["show_mask"] is False
    assert proc._show_mask is False
