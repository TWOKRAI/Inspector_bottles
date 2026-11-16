"""RunControlWidget — пульт запуска системы в главном окне (Task 2.3).

Состояние системы и причины рисуются по-русски из листьев ``system.run.*``;
кнопки ЗАПУСТИТЬ / ОСТАНОВИТЬ / Квитировать шлют команды ProcessManager.

Принцип 6: GUI ничего не запускает сам — виджет только шлёт команды PM через
объект ``commands`` (четыре метода ``run_*_async``) и рисует то, что PM опубликовал.

Модуль состоит из двух частей:
    ``build_view(snapshot, busy)`` — чистая модель без Qt (словарь листьев → ``RunView``);
    ``RunControlWidget``          — отрисовка ``RunView`` и обработка кликов.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from typing import Any

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from multiprocess_prototype.frontend.state.bindings import DELETED

_logger = logging.getLogger(__name__)

__all__ = ["BUSY_SAFETY_MS", "RunControlWidget", "RunView", "build_view"]

# Страховка «занято»: если после успешного ответа лист state так и не сменился,
# кнопки разблокируются сами через это время. Тест подменяет через monkeypatch.
BUSY_SAFETY_MS = 3000

_PREFIX = "system.run."

# Листья, которыми затравка из ответа ``system.run.status`` дополняет снимок.
_SEED_KEYS = ("state", "reasons", "start_allowed", "ack_allowed", "last_fault")

# state -> (имя по-русски, уровень цвета)
_STATES: dict[str, tuple[str, str]] = {
    "booting": ("Поднимается", "neutral"),
    "not_ready": ("Не готов", "warn"),
    "ready": ("Готов", "ok"),
    "running": ("Работает", "ok"),
    "stopping": ("Останавливается", "neutral"),
    "fault": ("Авария", "danger"),
    "shutting_down": ("Завершение", "neutral"),
}

_NO_DATA = "Нет данных"

# Коды отказа PM -> русский текст
_REFUSALS: dict[str, str] = {
    "not_ready": "система не готова",
    "already_running": "уже работает",
    "stopping": "идёт остановка",
    "fault_unacknowledged": "авария не квитирована",
    "fault_stopping": "идёт остановка после аварии",
    "no_fault": "аварии нет",
    "shutting_down": "система завершает работу",
}

_TEXT_NO_LINK = "нет связи"
_TEXT_NO_ANSWER = "нет ответа от системы"
_TEXT_REFUSED = "отказ"
_TEXT_FAULT_STOPPING = "идёт остановка"


@dataclass(frozen=True)
class RunView:
    """Готовое к отрисовке представление пульта (без Qt)."""

    state_text: str
    level: str  # neutral | ok | warn | danger
    start_enabled: bool
    start_tooltip: str
    stop_enabled: bool
    ack_visible: bool
    ack_enabled: bool
    detail_text: str
    indicators_text: str
    fault_text: str


_NO_DATA_VIEW = RunView(
    state_text=_NO_DATA,
    level="neutral",
    start_enabled=False,
    start_tooltip="",
    stop_enabled=False,
    ack_visible=False,
    ack_enabled=False,
    detail_text="",
    indicators_text="",
    fault_text="",
)


# ---------------------------------------------------------------------------
# Модель
# ---------------------------------------------------------------------------


def _valid_reasons(raw: Any) -> list[dict[str, Any]]:
    """Оставить из ``reasons`` только записи-словари; не список -> пусто."""
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _reason_text(entry: dict[str, Any]) -> str:
    """Текст причины записи; нет ключа/None -> пустая строка."""
    reason = entry.get("reason")
    return "" if reason is None else str(reason)


def _blocking_reasons(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Блокирующие причины: сначала ``failure``, затем ``check_function`` (порядок внутри сохранён)."""
    failures = [r for r in reasons if r.get("severity") == "failure"]
    checks = [r for r in reasons if r.get("severity") == "check_function"]
    return failures + checks


def _first_reason(raw_reasons: Any) -> str:
    """Текст первой годной записи списка причин; нет записей -> пусто."""
    reasons = _valid_reasons(raw_reasons)
    return _reason_text(reasons[0]) if reasons else ""


def _clock(value: Any) -> str | None:
    """Локальное ЧЧ:ММ:СС от метки времени; негодное значение -> None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return time.strftime("%H:%M:%S", time.localtime(value))
    except (OverflowError, OSError, ValueError):
        return None


def _indicators_text(reasons: list[dict[str, Any]]) -> str:
    """Индикаторы «вне допуска» / «обслуживание» (цвет аварии не используют)."""
    parts: list[str] = []
    out_of_spec = [_reason_text(r) for r in reasons if r.get("severity") == "out_of_spec"]
    if out_of_spec:
        parts.append("Вне допуска: " + "; ".join(out_of_spec))
    maintenance = [_reason_text(r) for r in reasons if r.get("severity") == "maintenance"]
    if maintenance:
        parts.append("Обслуживание: " + "; ".join(maintenance))
    return " · ".join(parts)


def _fault_text(last_fault: Any) -> str:
    """Строка «Последняя авария ЧЧ:ММ:СС — причина — (не) квитирована»."""
    if not isinstance(last_fault, dict):
        return ""
    at = _clock(last_fault.get("at"))
    text = f"Последняя авария {at if at is not None else '--:--:--'}"
    reason = _first_reason(last_fault.get("reasons"))
    if reason:
        text += f" — {reason}"
    acked = last_fault.get("acknowledged_at")
    if acked is None:
        text += " — не квитирована"
    else:
        acked_at = _clock(acked)
        text += f" — квитирована {acked_at}" if acked_at is not None else " — квитирована"
    return text


def build_view(snapshot: dict[str, Any], busy: bool) -> RunView:
    """Собрать представление пульта из снимка листьев ``system.run.*``.

    Args:
        snapshot: ``{state, reasons, start_allowed, ack_allowed, last_fault}``;
            любой ключ может отсутствовать, ввод любой формы не бросает.
        busy: команда оператора в полёте — кнопки неактивны.
    """
    state = snapshot.get("state")
    if not isinstance(state, str) or state not in _STATES:
        return _NO_DATA_VIEW

    state_text, level = _STATES[state]
    reasons = _valid_reasons(snapshot.get("reasons"))
    start_allowed = bool(snapshot.get("start_allowed"))
    ack_allowed = bool(snapshot.get("ack_allowed"))
    last_fault = snapshot.get("last_fault")

    ack_visible = state == "fault"
    detail_text = ""
    start_tooltip = ""
    if state == "fault":
        # В аварии правило ЗАПУСТИТЬ перекрыто: пока квитирование не разрешено,
        # PM ещё останавливает систему.
        if not ack_allowed:
            detail_text = _TEXT_FAULT_STOPPING
        elif isinstance(last_fault, dict):
            detail_text = _first_reason(last_fault.get("reasons"))
    elif not start_allowed:
        blocking = _blocking_reasons(reasons)
        if blocking:
            detail_text = _reason_text(blocking[0])
            lines = []
            for entry in blocking:
                node = entry.get("node")
                reason = _reason_text(entry)
                lines.append(f"{node}: {reason}" if node else reason)
            start_tooltip = "\n".join(lines)

    return RunView(
        state_text=state_text,
        level=level,
        start_enabled=start_allowed and state == "ready" and not busy,
        start_tooltip=start_tooltip,
        stop_enabled=state == "running" and not busy,
        ack_visible=ack_visible,
        ack_enabled=ack_visible and ack_allowed and not busy,
        detail_text=detail_text,
        indicators_text=_indicators_text(reasons) if state == "running" else "",
        fault_text=_fault_text(last_fault),
    )


def _refusal_text(result: Any) -> str:
    """Русский текст ответа-неуспеха на команду оператора.

    Нет ключа ``result`` (таймаут, исключение в пуле) -> «нет ответа от системы».
    """
    body = result.get("result") if isinstance(result, dict) else None
    if not isinstance(body, dict):
        return _TEXT_NO_ANSWER
    code = body.get("error")
    if isinstance(code, str) and code:
        text = _REFUSALS.get(code, f"{_TEXT_REFUSED}: {code}")
    else:
        text = _TEXT_REFUSED
    reason = _first_reason(body.get("reasons"))
    return f"{text}: {reason}" if reason else text


# ---------------------------------------------------------------------------
# Виджет
# ---------------------------------------------------------------------------


class RunControlWidget(QWidget):
    """Пульт запуска: состояние, причина, индикаторы, последняя авария, три кнопки.

    Листья ``system.run.*`` подаются через ``apply_leaf`` (fan-out подписка окна);
    команды уходят в объект ``commands`` (см. ``set_commands``).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RunControl")

        self._snapshot: dict[str, Any] = {}
        self._commands: Any = None
        self._busy = False
        self._click_seq = 0  # номер последнего клика: ответ старого клика busy не трогает
        self._busy_state: Any = None  # значение state на момент клика
        self._refusal = ""  # текст отказа/сбоя поверх detail_text
        self._level: str | None = None

        self._state_label = self._make_label("RunStateLabel")
        self._detail_label = self._make_label("RunDetailLabel")
        self._indicators_label = self._make_label("RunIndicatorsLabel")
        self._fault_label = self._make_label("RunFaultLabel")

        self._start_btn = self._make_button("RunStartButton", "ЗАПУСТИТЬ", "start")
        self._stop_btn = self._make_button("RunStopButton", "ОСТАНОВИТЬ", "stop")
        self._ack_btn = self._make_button("RunAckButton", "Квитировать", "ack")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._state_label)
        top.addWidget(self._detail_label, stretch=1)
        top.addWidget(self._indicators_label)
        top.addWidget(self._start_btn)
        top.addWidget(self._stop_btn)
        top.addWidget(self._ack_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(2)
        root.addLayout(top)
        root.addWidget(self._fault_label)

        # Страховка busy: единственный таймер, каждый клик перезапускает его,
        # поэтому таймер старого клика на busy нового не влияет.
        self._safety_timer = QTimer(self)
        self._safety_timer.setSingleShot(True)
        self._safety_timer.timeout.connect(self._on_safety_timeout)

        self._render()

    # -- Построение ----------------------------------------------------------

    def _make_label(self, name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(name)
        # Причины PM — данные, не разметка: «<b>x</b>» показываем как есть.
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _make_button(self, name: str, text: str, kind: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.clicked.connect(lambda _checked=False, k=kind: self._on_click(k))
        return button

    # -- Публичное API -------------------------------------------------------

    def set_commands(self, commands: Any) -> None:
        """Подключить объект команд (``run_*_async``) и запросить затравку статуса.

        Поздний GUI не получает ``last_fault`` из replay подписки, поэтому один раз
        спрашиваем ``system.run.status`` и добираем отсутствующие листья.
        """
        self._commands = commands
        if commands is not None:
            try:
                commands.run_status_async(self._on_seed_result)
            except Exception:
                # run_gui зовёт set_commands до цикла Qt: сбой затравки не должен ронять запуск.
                _logger.exception("RunControlWidget: не удалось отправить run_status_async")

    def apply_leaf(self, path: str, value: Any) -> None:
        """Принять лист ``system.run.*`` (``DELETED`` — узел удалён)."""
        key = path.removeprefix(_PREFIX)
        old_state = self._snapshot.get("state")
        if value is DELETED:
            self._snapshot.pop(key, None)
        else:
            self._snapshot[key] = value

        if key == "state":
            new_state = self._snapshot.get("state")
            if new_state != old_state:
                self._refusal = ""  # текст отказа живёт, пока значение state то же
            if self._busy and new_state != self._busy_state:
                self._release_busy()
        self._render()

    # -- Команды -------------------------------------------------------------

    def _on_click(self, kind: str) -> None:
        if self._busy:
            return
        if self._commands is None:
            self._refusal = _TEXT_NO_LINK
            self._render()
            return

        self._busy = True
        self._click_seq += 1
        seq = self._click_seq
        self._busy_state = self._snapshot.get("state")
        self._refusal = ""
        self._safety_timer.start(BUSY_SAFETY_MS)
        self._render()

        def on_result(result: dict[str, Any], seq: int = seq) -> None:
            self._on_command_result(seq, result)

        try:
            getattr(self._commands, f"run_{kind}_async")(on_result)
        except Exception:
            _logger.exception("RunControlWidget: не удалось отправить run_%s_async", kind)
            self._release_busy()
            self._refusal = _TEXT_NO_LINK
            self._render()

    def _on_command_result(self, seq: int, result: Any) -> None:
        """Ответ на клик; может прийти после закрытия окна."""
        if not shiboken6.isValid(self):
            return
        success = isinstance(result, dict) and bool(result.get("success"))
        current = seq == self._click_seq
        if success:
            # busy держится, пока state не сменится (порядок «ответ/дельта» не гарантирован)
            if current and self._busy and self._snapshot.get("state") != self._busy_state:
                self._release_busy()
        else:
            if current:
                # Устаревший отказ старого клика не затирает текст нового.
                self._refusal = _refusal_text(result)
                self._release_busy()
        self._render()

    def _on_seed_result(self, result: Any) -> None:
        """Ответ затравки ``system.run.status``: добирает только отсутствующие листья."""
        if not shiboken6.isValid(self):
            return
        if not isinstance(result, dict) or not result.get("success"):
            return  # ошибка/таймаут затравки — молча, виджет живёт по листам
        body = result.get("result")
        if not isinstance(body, dict):
            return
        for key in _SEED_KEYS:
            if key in body and key not in self._snapshot:
                self._snapshot[key] = body[key]
        self._render()

    def _on_safety_timeout(self) -> None:
        if not shiboken6.isValid(self):
            return
        if self._busy:
            self._release_busy()
            self._render()

    def _release_busy(self) -> None:
        self._busy = False
        self._safety_timer.stop()

    # -- Отрисовка -----------------------------------------------------------

    def _render(self) -> None:
        view = build_view(self._snapshot, self._busy)

        self._state_label.setText(view.state_text)
        if view.level != self._level:
            self._level = view.level
            self._state_label.setProperty("level", view.level)
            style = self._state_label.style()
            if style is not None:
                style.unpolish(self._state_label)
                style.polish(self._state_label)

        self._detail_label.setText(self._refusal or view.detail_text)
        self._indicators_label.setText(view.indicators_text)
        self._indicators_label.setVisible(bool(view.indicators_text))
        self._fault_label.setText(view.fault_text)
        self._fault_label.setVisible(bool(view.fault_text))

        self._start_btn.setEnabled(view.start_enabled)
        # Подсказка рисуется Qt как rich text, если похожа на HTML: причины PM — данные,
        # поэтому экранируем, а переводы строк сохраняем через white-space:pre.
        tooltip = view.start_tooltip
        if tooltip:
            tooltip = f"<p style='white-space:pre'>{html.escape(tooltip)}</p>"
        self._start_btn.setToolTip(tooltip)
        self._stop_btn.setEnabled(view.stop_enabled)
        self._ack_btn.setVisible(view.ack_visible)
        self._ack_btn.setEnabled(view.ack_enabled)
