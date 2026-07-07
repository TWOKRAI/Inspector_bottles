"""Generic JSON-редактор для list/dict полей (Вариант Б).

Выделено из `forms/factory.py` (Task F.5, дословный перенос). getter возвращает
РАСПАРСЕННЫЙ объект (не строку); при невалидном JSON — последнее валидное
значение + красная рамка. form_ctx игнорируется (legacy-стиль, как str/path).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

from ..field_editor import FieldEditor
from ._common import _make_label
from .kinds import _safe_default


class _JsonTextEdit(QPlainTextEdit):
    """QPlainTextEdit с commit-семантикой: committed эмитится при потере фокуса.

    Нужно для generic-редактора list/dict — write выполняется на commit, а не на
    каждый символ (иначе getter парсил бы незавершённый JSON на каждом нажатии).
    """

    committed = Signal()

    def focusOutEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        super().focusOutEvent(event)
        self.committed.emit()


def _json_dumps(value: Any) -> str:
    """Сериализовать value в pretty-JSON. None → пустая строка."""
    import json

    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _set_json_error(widget: QWidget, on: bool) -> None:
    """Подсветить редактор красной рамкой при невалидном JSON."""
    widget.setStyleSheet("border: 1px solid #c0392b;" if on else "")


def _build_json(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """Generic JSON-редактор для list/dict полей (regions, expected_regions, default_region).

    КЛЮЧЕВОЕ: getter() возвращает РАСПАРСЕННЫЙ объект (list/dict), а не строку —
    иначе в config плагина уехала бы строка вместо list[dict]. При невалидном JSON
    getter возвращает последнее валидное значение (мусор в config не попадёт) и
    подсвечивает редактор красной рамкой + tooltip с текстом ошибки.

    change_signal = committed (потеря фокуса), а не textChanged — write на commit.
    form_ctx игнорируется: generic-путь без binding-aware моста (как str/path legacy).
    """
    import json

    te = _JsonTextEdit(parent)
    te.setFixedHeight(120)
    te.setPlaceholderText('[] или [{"name": "left", "x": 0, "y": 0, "width": 320, "height": 480}]')

    default = _safe_default(field_info)
    # Кэш последнего валидного значения — getter вернёт его при ошибке парсинга.
    state: dict[str, Any] = {"value": default}
    te.setPlainText(_json_dumps(default))

    def _getter() -> Any:
        text = te.toPlainText().strip()
        if not text:
            _set_json_error(te, False)
            te.setToolTip("")
            return state["value"]
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            _set_json_error(te, True)
            te.setToolTip(f"Невалидный JSON: {exc}")
            return state["value"]
        state["value"] = parsed
        _set_json_error(te, False)
        te.setToolTip("")
        return parsed

    def _setter(v: Any) -> None:
        state["value"] = v
        te.blockSignals(True)
        te.setPlainText(_json_dumps(v))
        te.blockSignals(False)
        _set_json_error(te, False)
        te.setToolTip("")

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=te,
        getter=_getter,
        setter=_setter,
        change_signal=te.committed,
        label=label,
    )
