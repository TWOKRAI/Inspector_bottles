"""CloseCoordinator: крестик ждёт остановки системы (Task 1.1, plans/2026-10-20_gui-graceful-close).

Машина состояний закрытия главного окна::

    RUNNING ──крестик──▶ CONFIRMING ──«Отмена»/сбой вопроса──▶ RUNNING
                            │
                            ├─ подтверждено ─▶ send_shutdown ─▶ STOPPING ─▶ (все дети мертвы) ─▶ CLOSING
                            └─ сбой send_shutdown / safety-тик ──────────────────────────────▶ CLOSING

Все эффекты внедряются вызовами (``confirm_discard``, ``send_shutdown``, ``poll_status``, ``ask_force_stop``,
``force_stop``, ``quit_app``, ``on_shutdown_sent``): так координатор тестируется без живого бэкенда.

Опрос ``poll_status`` идёт на ``RequestRunner`` (по умолчанию общий ``QThreadPool``), результат приходит в главный
поток. В полёте не более одного запроса. На каждом тике того же ``QTimer`` проверяется сторож тишины:
``last = max(t_send, t_last_success, t_wait_click, t_force)``; ``clock() - last >= no_answer_s`` — вопрос
оператору, «Остановить» (``force_stop``), а после ``force_stop`` — ``commit_close`` (PM мёртв или завис).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from multiprocess_framework.modules.logger_module import get_std_logger

__all__ = [
    "FORCE_STOP_QUESTION",
    "CloseCoordinator",
    "CloseState",
    "Closable",
    "ask_force_stop_dialog",
]

_log = get_std_logger("gui")

FORCE_STOP_QUESTION = (
    "Бэкенд не ответил на команду остановки за 2 с. Остановить систему принудительно? "
    "Шаги подготовки («домой») будут пропущены."
)
_PROGRESS_TITLE = "Остановка системы"
_POLL_TIMEOUT_S = 1.0


class Closable(Protocol):
    """Ручка открытого вопроса: ``close()`` закрывает его без ответа оператора."""

    def close(self) -> None: ...


class CloseState(str, Enum):
    RUNNING = "running"
    CONFIRMING = "confirming"
    STOPPING = "stopping"
    CLOSING = "closing"


class _StopProgressDialog(QProgressDialog):
    """Прогресс остановки: без кнопки отмены, Esc / ``reject`` / крестик диалога его не закрывают.

    ``QProgressDialog`` по умолчанию закрывается по Esc и сам прячется по ``autoClose``/``autoReset``;
    здесь закрывает его только координатор (``finish``).
    """

    def __init__(self, parent: QWidget | None, *, modal: bool = True) -> None:
        super().__init__(parent)
        self._allow_close = False
        self.setWindowTitle(_PROGRESS_TITLE)
        self.setLabelText(f"{_PROGRESS_TITLE}…")
        self.setCancelButton(None)
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setRange(0, 0)  # N ещё неизвестно: «занят» до первого успешного ответа
        # Без присмотра — немодальный: сторож модалок (unattended.install_modal_watchdog) берёт
        # activeModalWidget() и писал бы WARNING «modal_closed» каждые 250 мс всего ожидания.
        self.setWindowModality(Qt.WindowModality.WindowModal if modal else Qt.WindowModality.NonModal)

    def reject(self) -> None:  # noqa: D401 — Qt-хук: Esc и сторож модалок зовут reject
        """Esc не закрывает диалог остановки."""

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt-хук
        if self._allow_close:
            super().closeEvent(event)
        else:
            event.ignore()

    def finish(self) -> None:
        self._allow_close = True
        self.hide()
        self.deleteLater()


def ask_force_stop_dialog(parent: QWidget | None, on_answer: Callable[[bool], None]) -> QMessageBox:
    """Настоящий ``ask_force_stop``: немодальный для цикла событий вопрос (``open()``, не ``exec()``).

    «Остановить» (по умолчанию) → ``on_answer(True)``; «Подождать», Esc, крестик → ``on_answer(False)``.
    Возвращает сам ``QMessageBox`` как ручку с ``close()``. Ответ после ``close()`` координатором
    координатор отбрасывает сам (ручка уже не текущая).
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(_PROGRESS_TITLE)
    box.setText(FORCE_STOP_QUESTION)
    stop_button = box.addButton("Остановить", QMessageBox.ButtonRole.AcceptRole)
    wait_button = box.addButton("Подождать", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(stop_button)
    box.setEscapeButton(wait_button)
    box.setWindowModality(Qt.WindowModality.WindowModal)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def _finished(_result: int) -> None:
        on_answer(box.clickedButton() is stop_button)

    box.finished.connect(_finished)
    box.open()
    return box


class CloseCoordinator(QObject):
    """Закрытие окна: вопрос о правках → ``system.shutdown`` → ожидание детей → ``quit_app``."""

    def __init__(
        self,
        window: Any,
        *,
        confirm_discard: Callable[[], bool],
        send_shutdown: Callable[[], dict],
        poll_status: Callable[[float], dict],
        ignore_names: frozenset[str],
        ask_force_stop: Callable[[Callable[[bool], None]], Closable],
        force_stop: Callable[[], None],
        quit_app: Callable[[], None],
        on_shutdown_sent: Callable[[], None],
        unattended: bool = False,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_ms: int = 250,
        no_answer_s: float = 2.0,
        request_runner: Any | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._confirm_discard = confirm_discard
        self._send_shutdown = send_shutdown
        self._poll_status = poll_status
        self._ignore_names = frozenset(ignore_names)
        self._ask_force_stop = ask_force_stop
        self._force_stop = force_stop
        self._quit_app = quit_app
        self._on_shutdown_sent = on_shutdown_sent
        self._unattended = unattended
        self._clock = clock
        self._no_answer_s = no_answer_s

        if request_runner is None:
            from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

            request_runner = RequestRunner(self)  # общий QThreadPool.globalInstance()
        self._runner = request_runner

        self._state = CloseState.RUNNING
        self._restart_requested = False
        # Опрос и сторож тишины (шаги 4-5)
        self._in_flight = False
        self._t_send: float | None = None
        self._t_last_success: float | None = None
        self._t_wait_click: float | None = None
        self._t_force: float | None = None
        self._forced = False
        self._question: Closable | None = None
        self._question_token: object | None = None
        self._progress: _StopProgressDialog | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ #
    #  Публичное                                                          #
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> CloseState:
        return self._state

    @property
    def restart_requested(self) -> bool:
        """Закрытие начато подтверждённым ``request_restart()`` (composition root ставит ``_restart_ui``)."""
        return self._restart_requested

    def request_close(self) -> None:
        """Крестик: вопрос о правках → ``system.shutdown`` → ``STOPPING``. Вне ``RUNNING`` — ничего."""
        if not self._confirm():
            return
        _log.info("закрытие: подтверждено")
        try:
            self._send_shutdown()
        except Exception as exc:  # noqa: BLE001 — сбой отправки: закрываемся прежним путём
            _log.error(
                f"закрытие: system.shutdown не отправлен ({type(exc).__name__}: {exc}) — "
                "окно закрывается, систему гасит прежний путь GuiProcess._request_system_shutdown"
            )
            self.commit_close()
            return
        self._t_send = self._clock()
        _log.info("закрытие: system.shutdown отправлен")
        self._on_shutdown_sent()
        self._state = CloseState.STOPPING
        self._show_progress()
        self._timer.start()

    def request_restart(self) -> None:
        """Рестарт UI: тот же вопрос о правках, затем ``commit_close()`` без ``system.shutdown``."""
        if not self._confirm():
            return
        _log.info("закрытие: подтверждён рестарт UI (без system.shutdown)")
        self._restart_requested = True
        self.commit_close()

    def backend_gone(self) -> None:
        """Бэкенд остановлен извне (``should_stop``): закрыться сразу, без вопросов."""
        if self._state not in (CloseState.RUNNING, CloseState.CONFIRMING):
            return
        _log.info("закрытие: бэкенд остановлен извне — окно закрывается без вопросов")
        self.commit_close()

    def commit_close(self) -> None:
        """``→ CLOSING``, затем ``quit_app()`` ровно один раз за закрытие."""
        if self._state is CloseState.CLOSING:
            return
        self._state = CloseState.CLOSING
        self._timer.stop()
        self._drop_question()
        if self._progress is not None:
            self._progress.finish()
            self._progress = None
        self._quit_app()
        _log.info("закрытие: окно скрыто")

    def on_safety_tick(self, should_stop: bool) -> None:
        """Тик safety-таймера (1000 мс в app.py). В ``STOPPING`` ожидание детей не прерывает."""
        if should_stop:
            self.backend_gone()

    # ------------------------------------------------------------------ #
    #  Вопрос о правках                                                   #
    # ------------------------------------------------------------------ #

    def _confirm(self) -> bool:
        """``RUNNING → CONFIRMING`` и вопрос. True — продолжать (состояние всё ещё ``CONFIRMING``)."""
        if self._state is not CloseState.RUNNING:
            return False
        self._state = CloseState.CONFIRMING
        try:
            ok = self._confirm_discard()
        except Exception as exc:  # noqa: BLE001 — сбой вопроса: остаёмся работать
            _log.error(f"закрытие: вопрос о несохранённых правках упал ({type(exc).__name__}: {exc})")
            ok = False
        # За время модального вопроса safety-тик мог перевести в CLOSING: бэкенд ушёл — он побеждает.
        if self._state is not CloseState.CONFIRMING:
            return False
        if not ok:
            self._state = CloseState.RUNNING
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Опрос и сторож тишины                                              #
    # ------------------------------------------------------------------ #

    def _on_tick(self) -> None:
        if self._state is not CloseState.STOPPING:
            return
        self._check_silence()
        if self._state is not CloseState.STOPPING or self._in_flight:
            return
        self._in_flight = True
        poll = self._poll_status
        self._runner.submit(lambda: poll(_POLL_TIMEOUT_S), self._on_poll_result)

    def _on_poll_result(self, result: dict[str, Any]) -> None:
        """Главный поток: результат ``poll_status``."""
        self._in_flight = False
        if self._state is not CloseState.STOPPING:
            return
        if not isinstance(result, dict) or result.get("success") is not True:
            return  # таймаут / ошибка — не ответ
        self._t_last_success = self._clock()
        if self._question is not None:
            # Ответ PM пришёл раньше оператора: «Подождать» без сдвига t_wait_click.
            self._drop_question()
        processes = result.get("processes")
        if not isinstance(processes, dict) or not processes:
            return
        children = {
            name: rec
            for name, rec in processes.items()
            if name not in self._ignore_names and isinstance(rec, dict) and rec.get("alive") is not None
        }
        alive = [name for name, rec in children.items() if rec.get("alive") is True]
        self._update_progress(len(children) - len(alive), len(children))
        if not alive:
            _log.info(f"закрытие: все процессы остановлены ({len(children)})")
            self.commit_close()

    def _check_silence(self) -> None:
        stamps = [t for t in (self._t_send, self._t_last_success, self._t_wait_click, self._t_force) if t is not None]
        if not stamps or self._clock() - max(stamps) < self._no_answer_s:
            return
        if self._forced:
            _log.warning(
                f"закрытие: бэкенд молчит {self._no_answer_s} с после принудительной остановки — "
                "окно закрывается, не дождавшись детей"
            )
            self.commit_close()
            return
        if self._question is not None:
            return  # вопрос открыт — повторно не спрашиваем
        if self._unattended:
            self._do_force("без присмотра")
            return
        token = object()
        self._question_token = token
        try:
            self._question = self._ask_force_stop(lambda stop: self._on_operator_answer(token, stop))
        except Exception as exc:  # noqa: BLE001 — вопрос не показать: действуем как без присмотра
            _log.error(f"закрытие: вопрос о принудительной остановке не показан ({type(exc).__name__}: {exc})")
            self._question_token = None
            self._do_force("вопрос не показан")

    def _on_operator_answer(self, token: object, stop: bool) -> None:
        if token is not self._question_token or self._state is not CloseState.STOPPING:
            return  # вопрос уже закрыт координатором (ответ PM) или закрытие завершено
        self._question = None
        self._question_token = None
        if stop:
            self._do_force("оператор")
        else:
            self._t_wait_click = self._clock()
            _log.info("закрытие: оператор выбрал «Подождать»")

    def _do_force(self, who: str) -> None:
        self._forced = True
        self._t_force = self._clock()
        _log.warning(f"закрытие: принудительная остановка ({who}) — взводится общий system_stop_event")
        try:
            self._force_stop()
        except Exception as exc:  # noqa: BLE001 — хвост сторожа всё равно закроет окно
            _log.error(f"закрытие: force_stop упал ({type(exc).__name__}: {exc})")

    def _drop_question(self) -> None:
        """Закрыть открытый вопрос без ответа оператора; поздний ответ ручки отбрасывается."""
        handle = self._question
        self._question = None
        self._question_token = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception as exc:  # noqa: BLE001 — ручка уже разрушена
            _log.error(f"закрытие: вопрос не закрылся ({type(exc).__name__}: {exc})")

    # ------------------------------------------------------------------ #
    #  Прогресс                                                           #
    # ------------------------------------------------------------------ #

    def _show_progress(self) -> None:
        parent = self._window if isinstance(self._window, QWidget) else None
        self._progress = _StopProgressDialog(parent, modal=not self._unattended)
        self._progress.show()

    def _update_progress(self, stopped: int, total: int) -> None:
        if self._progress is None:
            return
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(min(stopped, max(total, 1)))
        text = f"{_PROGRESS_TITLE}… {stopped} из {total}"
        self._progress.setWindowTitle(text)
        self._progress.setLabelText(text)
