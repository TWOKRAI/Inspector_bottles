"""Шаги загрузки GUI: лист ``system.progress.gui`` (задача 2.6). Без Qt."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.process_module.progress import ProgressTracker, progress_path

#: Шаги ``run_gui`` и их веса в шкале GUI.
GUI_STEPS: list[tuple[str, int]] = [("qt", 10), ("plugins", 40), ("state", 20), ("window", 30)]


class GuiStartupProgress:
    """Писатель шкалы загрузки GUI. Ни один метод не бросает; после ``done`` писатель не зовётся.

    Новый запуск ``run_gui`` создаёт новый объект. Только главный поток GUI.
    """

    def __init__(self, writer: Callable[[str, dict], object], log: Callable[[str], object]) -> None:
        self._writer = writer
        self._log = log
        self._tracker = ProgressTracker(GUI_STEPS)
        self._finished = False

    @classmethod
    def for_process(cls, process: Any) -> GuiStartupProgress:
        """Писать через ``process._gui_state_proxy.set``; прокси нет — записи молча пропускаются."""

        def _write(path: str, leaf: dict) -> None:
            proxy = getattr(process, "_gui_state_proxy", None)
            if proxy is not None:
                proxy.set(path, leaf)

        return cls(_write, lambda text: process._log_warning(text, module="startup"))

    def step(self, name: str) -> None:
        """Шаг ``name`` из ``GUI_STEPS`` пройден."""
        if self._finished:
            return
        try:
            self._writer(progress_path("gui"), self._tracker.advance(name))
        except Exception as exc:  # noqa: BLE001 — шкала не имеет права уронить GUI
            self._warn(f"шкала загрузки GUI: шаг '{name}' не записан: {exc}")

    def done(self, label: str = "") -> None:
        """Первое окно появилось: 100 % и ``done``. Повторный вызов — пустой."""
        if self._finished:
            return
        self._finished = True
        try:
            self._writer(progress_path("gui"), self._tracker.finish(label))
        except Exception as exc:  # noqa: BLE001
            self._warn(f"шкала загрузки GUI: итог не записан: {exc}")

    def _warn(self, text: str) -> None:
        try:
            self._log(text)
        except Exception:  # noqa: BLE001 — логгер сломан: последнее средство — stderr
            print(text, file=sys.stderr)
