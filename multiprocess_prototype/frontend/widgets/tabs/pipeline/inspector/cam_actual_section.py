# -*- coding: utf-8 -*-
"""CamActualSection — блок «Камера (actual)» инспектора (F.6, разрез god-файла).

Read-only телеметрия того, что камера реально применила (cap.get): FPS, разрешение,
экспозиция, усиление, кодек. Привязка к реактивному дереву состояния по путям
``processes.{proc}.state.cam.actual.*`` через GuiStateBindings. Показывается только
для camera_service-ноды.

Инкапсулирует 6 подписок и их teardown — закрывает находку Н-4 (при разрушении панели
с активной camera-нодой bind-хэндлы оставались жить в GuiStateBindings: утечка + запись
в мёртвые QLabel через weakref). ``dispose()`` снимает подписки в destroyed-пути (чистый
Python, без Qt-вызовов на уже удалённых дочерних виджетах).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

# Строки блока: ключ пути state store → подпись в форме.
_ROWS = (
    ("fps", "FPS:"),
    ("resolution", "Разрешение:"),
    ("exposure", "Экспозиция:"),
    ("gain", "Усиление:"),
    ("fourcc", "Кодек:"),
)


class CamActualSection(QWidget):
    """Секция actual-телеметрии камеры с самодостаточным управлением подписками.

    Использование:
        section = CamActualSection()
        section.set_bindings(bindings)          # GuiStateBindings | None (из set_services)
        section.show_for("camera_0")            # bind 6 путей + показать
        section.hide_and_unbind()               # unbind + скрыть + сбросить метки
        section.dispose()                       # только unbind (destroyed-путь, без Qt)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bindings: Any = None
        # Дескрипторы активных подписок actual (для отписки при смене ноды / teardown).
        self._handles: list[Any] = []
        # Разрешение собирается из width+height, приходящих раздельно — общее состояние.
        self._cam_res: dict[str, int] = {"width": 0, "height": 0}
        self._labels: dict[str, QLabel] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        cam_title = QLabel("Камера (actual)")
        cam_title.setProperty("role", "plugin-name")
        layout.addRow(cam_title)
        for key, caption in _ROWS:
            lbl = QLabel("—")
            self._labels[key] = lbl
            layout.addRow(caption, lbl)
        self.setVisible(False)

    def set_bindings(self, bindings: Any) -> None:
        """Передать GuiStateBindings (приходит из set_services позже __init__)."""
        self._bindings = bindings

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def show_for(self, process_name: str) -> None:
        """Показать блок и привязать метки к state store.

        Пути: processes.{proc}.state.cam.actual.{fps,width,height,exposure,gain,fourcc}.
        Разрешение собирается из width+height отдельным форматтером на оба пути.
        """
        self.hide_and_unbind()
        if self._bindings is None or not process_name:
            # Без bindings actual недоступен (нет live-подписки) — блок не показываем.
            return
        self.setVisible(True)
        base = f"processes.{process_name}.state.cam.actual"

        def _num(lbl: QLabel, unit: str = ""):
            return lambda v: f"{float(v):.0f}{unit}" if isinstance(v, (int, float)) else str(v)

        self._handles.append(
            self._bindings.bind(
                f"{base}.fps", self._labels["fps"], "text", formatter=_num(self._labels["fps"], " fps")
            )
        )
        self._handles.append(
            self._bindings.bind(
                f"{base}.exposure", self._labels["exposure"], "text", formatter=_num(self._labels["exposure"])
            )
        )
        self._handles.append(
            self._bindings.bind(
                f"{base}.gain", self._labels["gain"], "text", formatter=_num(self._labels["gain"])
            )
        )
        self._handles.append(self._bindings.bind(f"{base}.fourcc", self._labels["fourcc"], "text"))

        # Разрешение: width и height приходят раздельно → обновляем общую метку.
        self._cam_res = {"width": 0, "height": 0}

        def _res_update(key: str):
            def _fmt(v: Any) -> str:
                try:
                    self._cam_res[key] = int(float(v))
                except (TypeError, ValueError):
                    pass
                return f"{self._cam_res['width']}×{self._cam_res['height']}"

            return _fmt

        self._handles.append(
            self._bindings.bind(f"{base}.width", self._labels["resolution"], "text", formatter=_res_update("width"))
        )
        self._handles.append(
            self._bindings.bind(f"{base}.height", self._labels["resolution"], "text", formatter=_res_update("height"))
        )

    def hide_and_unbind(self) -> None:
        """Скрыть блок, снять подписки и сбросить метки (штатная смена ноды)."""
        self._unbind()
        self.setVisible(False)
        for lbl in self._labels.values():
            lbl.setText("—")

    def dispose(self) -> None:
        """Teardown: снять cam-подписки (Н-4). Идемпотентен.

        Намеренно НЕ трогает Qt-виджеты (setVisible/setText): в destroyed-пути дочерние
        виджеты уже удалены, обращение к ним дало бы RuntimeError. Снимаем только
        подписки — это чистый Python.
        """
        self._unbind()

    # ------------------------------------------------------------------ #
    #  Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _unbind(self) -> None:
        """Снять подписки actual-телеметрии (баланс bind/unbind, Н-4).

        GuiStateBindings.unbind() не бросает (ValueError ловится внутри). Чистый Python —
        безопасно и после разрушения виджетов (destroyed-путь).
        """
        if self._bindings is not None:
            for h in self._handles:
                self._bindings.unbind(h)
        self._handles = []
