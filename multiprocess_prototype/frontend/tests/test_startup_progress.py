"""Слепая приёмка задачи 2.6: шаги прогресса GUI (``frontend.startup_progress``).

Написано до реализации по ``tasks/2.6.md`` (DESIGN п.6, REDS, «Публичные имена»). Qt не нужен.
"""

from __future__ import annotations


def test_steps_done_idempotent_never_raises():
    from multiprocess_prototype.frontend.startup_progress import GUI_STEPS, GuiStartupProgress

    assert GUI_STEPS == [("qt", 10), ("plugins", 40), ("state", 20), ("window", 30)]

    writes: list = []
    logs: list = []
    progress = GuiStartupProgress(lambda path, leaf: writes.append((path, dict(leaf))), logs.append)

    progress.step("qt")
    assert len(writes) == 1
    path, leaf = writes[-1]
    assert path == "system.progress.gui"
    assert leaf["percent"] == 10
    assert leaf["done"] is False

    progress.step("plugins")
    assert len(writes) == 2
    path, leaf = writes[-1]
    assert path == "system.progress.gui"
    assert leaf["percent"] == 50
    assert leaf["done"] is False

    progress.done("ожидание пользователя")
    assert len(writes) == 3
    path, leaf = writes[-1]
    assert path == "system.progress.gui"
    assert leaf["percent"] == 100
    assert leaf["done"] is True
    assert leaf["label"] == "ожидание пользователя"

    progress.step("window")
    progress.done()
    assert len(writes) == 3  # после done писатель не зван

    attempts: list = []
    broken_logs: list = []

    def _broken_writer(path, leaf):
        attempts.append(path)
        raise RuntimeError("писатель сломан")

    broken = GuiStartupProgress(_broken_writer, broken_logs.append)
    broken.step("qt")  # исключения нет
    assert attempts == ["system.progress.gui"]
    assert len(broken_logs) >= 1

    unknown_logs: list = []
    unknown = GuiStartupProgress(lambda path, leaf: None, unknown_logs.append)
    unknown.step("нет такого шага")  # исключения нет
    assert len(unknown_logs) >= 1
