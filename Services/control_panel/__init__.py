"""Services.control_panel — сервис «Пульт»: GUI-контролы → сигналы в pipeline.

Назначение: пользователь во вкладке Services → «Пульт» создаёт контролы (кнопка,
тумблер, слайдер, поле числа/текста) и оперирует ими. Нода ``control_panel`` в
pipeline эмитит значение контрола на его выходной порт (out_1..out_N) при операции;
порт вяжется к потребителю в редакторе Pipeline (координаты роботу, слово, триггер…).

Архитектура (зеркалит Services.phone_gateway, но БЕЗ HTTP — чисто GUI):
    controls.py  — ControlSpec: тип/порт/значение + валидация/коэрция (core)
    plugin/      — ControlPanelPlugin (source): дренит pending-эмиты в produce()

Публичный API:
    ControlSpec, parse_controls, controls_to_dicts
"""

from __future__ import annotations

from Services.control_panel.controls import ControlSpec, controls_to_dicts, parse_controls

__all__ = ["ControlSpec", "parse_controls", "controls_to_dicts"]
