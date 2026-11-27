# -*- coding: utf-8 -*-
"""VfdWidgetController — проводка VfdControlWidget <-> VfdPresenter.

Связывает сигналы виджета с командами presenter; bindings на state-пути
devices.state.<id>.{status,conn,last_error}; перепривязка при смене
устройства в комбо. UX-gating: DRAW-режим робота-носителя.
comm_errors — с дельтой за период (перенесено из robot/controller).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QTimer

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.reply import unwrap_reply

from .presenter import VfdPresenter
from .widget import VfdControlWidget

# н5 ревью Fable (ADR-PH-001): порог устаревания данных hub.
# Если time.time() - ts > _STALE_THRESHOLD_S, данные считаются stale
# независимо от quality-поля (hub мог упасть и quality «замёрз»).
_STALE_THRESHOLD_S = 3.0

# Отказ команды без текста от обработчика (таймаут, ошибка транспорта).
_REFUSAL_DEFAULT = "ПЧ: команда отклонена"


class VfdWidgetController:
    """Связывает виджет ПЧ с presenter + bindings."""

    def __init__(
        self,
        widget: VfdControlWidget,
        presenter: VfdPresenter,
        *,
        bindings: Any = None,
    ) -> None:
        self._widget = widget
        self._presenter = presenter
        self._bindings = bindings
        self._device_id: str | None = None
        self._last_comm_errors: int | None = None
        self._status_handles: list[Any] = []
        self._fanout_handles: list[Any] = []  # bind_fanout снимается только через unbind_fanout

        # н5 ревью Fable: QTimer для периодической проверки устаревания
        # данных. Если hub упал — пуши прекращаются, но индикатор
        # должен перейти в stale через _STALE_THRESHOLD_S.
        # bug-hunt A-5: без Qt-parent намеренно (тесты конструируют
        # controller с MagicMock-виджетом — QTimer(parent) требует реальный
        # QObject). Явный stop() гарантирован через unbind(), вызываемый из
        # DeviceDetailPage.cleanup() при снятии страницы устройства со стека
        # (см. devices_common/master_detail.py, vfd/section.py).
        self._last_status_ts: float | None = None
        self._stale_timer = QTimer()
        self._stale_timer.setInterval(2000)  # 2 с
        self._stale_timer.timeout.connect(self._check_stale)

        self._connect()

    def _connect(self) -> None:
        w = self._widget
        w.run_requested.connect(self._on_run)
        w.set_freq_requested.connect(self._on_set_freq)
        w.stop_requested.connect(self._on_stop)
        w.reset_fault_requested.connect(self._on_reset)
        w.refresh_requested.connect(self._on_refresh)

    # ------------------------------------------------------------------ #
    # Смена устройства
    # ------------------------------------------------------------------ #

    def set_device(self, device_id: str | None) -> None:
        """Переключить на другое устройство: перепривязать bindings, обновить meta."""
        self._unbind_state()
        if device_id != self._device_id:
            self._widget.set_refusal("")
        self._device_id = device_id
        self._last_comm_errors = None
        self._last_status_ts = None
        if not device_id:
            self._stale_timer.stop()
            self._widget.set_status("ПЧ: устройство не выбрано.")
            self._widget.set_controls_enabled(False, "Выберите устройство.")
            return
        self._bind_state(device_id)
        self._stale_timer.start()
        # Запросить describe для лимитов частоты и gating
        self._presenter.device_describe(device_id, self._on_describe)

    # ------------------------------------------------------------------ #
    # Bindings на state-пути
    # ------------------------------------------------------------------ #

    def unbind(self) -> None:
        """Остановить таймер и отвязать bindings (при скрытии вкладки)."""
        self._stale_timer.stop()
        self._unbind_state()

    def _check_stale(self) -> None:
        """н5: периодическая проверка устаревания данных (QTimer callback).

        Если hub упал и пуши прекратились, через _STALE_THRESHOLD_S
        индикатор переходит в stale.
        """
        if self._last_status_ts is None:
            return
        age = time.time() - self._last_status_ts
        if age > _STALE_THRESHOLD_S:
            self._widget.set_quality(
                f"Нет связи с hub (данные устарели на {age:.1f} с). Процесс devices может быть недоступен."
            )

    def _unbind_state(self) -> None:
        if self._bindings is not None:
            for h in self._status_handles:
                try:
                    self._bindings.unbind(h)
                except Exception:
                    pass
            for fh in self._fanout_handles:
                try:
                    self._bindings.unbind_fanout(fh)
                except Exception:
                    pass
        self._status_handles.clear()
        self._fanout_handles.clear()

    def _bind_state(self, device_id: str) -> None:
        """Привязать виджет к devices.state.<id>.{status,conn,last_error}."""
        self._unbind_state()
        if self._bindings is None:
            return
        base = f"devices.state.{device_id}"

        # Статус ПЧ (push) — вызываем _on_status_push
        if hasattr(self._bindings, "bind_fanout"):
            self._fanout_handles.append(
                self._bindings.bind_fanout(
                    f"{base}.status",
                    self._on_status_push,
                    owner=self._widget,
                )
            )

        # Conn
        h = self._bindings.bind(
            f"{base}.conn",
            self._widget._lbl_conn,
            "text",
            formatter=lambda v: f"Подключение: {_conn_text(v)}",
        )
        self._status_handles.append(h)

        # Last error
        h = self._bindings.bind(
            f"{base}.last_error",
            self._widget._lbl_error,
            "text",
            formatter=lambda v: f"Ошибка: {v}" if v else "",
        )
        self._status_handles.append(h)

    def _on_status_push(self, _path: str, value: Any) -> None:
        """Callback для push-статуса ПЧ из state-дерева."""
        if not isinstance(value, dict):
            return
        # н5: запомнить время последнего пуша для stale-timer
        self._last_status_ts = time.time()
        self._apply_vfd_status(value)

    def _apply_vfd_status(self, vfd: dict) -> None:
        """Обновить виджет по snapshot статуса ПЧ.

        Узел из read-model может быть неполным (Task 2.8f: стартовый replay потерян,
        ``merge`` шлёт только изменившиеся листья). Отсутствующее поле (или None —
        прямое подключение без моста) показывается как неизвестное: «?» для RUN/STOP,
        «—» для чисел и кода аварии. STOP, ноль и «нет аварии» не подставляются.
        """
        comm_raw = vfd.get("comm_errors")
        comm_text = "—"
        if comm_raw is not None:
            comm = int(comm_raw)
            comm_text = str(comm)
            if self._last_comm_errors is not None:
                comm_text += f" (+{max(0, comm - self._last_comm_errors)})"
            self._last_comm_errors = comm  # без значения прежняя база дельты сохраняется

        running_raw = vfd.get("running")
        running = "?" if running_raw is None else ("RUN" if running_raw else "STOP")
        fault = vfd.get("fault")
        if fault is None:
            fault_text = "  авария=—"
        else:
            fault_text = f"  АВАРИЯ=0x{int(fault):04X}" if fault else ""
        hb = vfd.get("heartbeat")
        hb_text = "—" if hb is None else str(hb)

        self._widget.set_status(
            f"[{running}] f={_num(vfd.get('out_freq_hz'), '.2f')} Гц  "
            f"I={_num(vfd.get('current_a'), '.1f')} А  "
            f"Udc={_num(vfd.get('dcbus_v'), '.1f')} В  "
            f"hb={hb_text}  rsErr={comm_text}{fault_text}"
        )

        # Quality + проверка возраста ts (н5/ADR-PH-001)
        quality = vfd.get("quality", "")
        ts = vfd.get("ts")
        ts_stale = False
        if ts is not None:
            age = time.time() - float(ts)
            if age > _STALE_THRESHOLD_S:
                ts_stale = True

        if ts_stale:
            self._widget.set_quality(
                f"Нет связи с hub (данные устарели на {age:.1f} с). Процесс devices может быть недоступен."
            )
        elif quality == "good":
            self._widget.set_quality("Данные актуальны.")
        elif quality == "stale":
            reason = vfd.get("reason", "")
            self._widget.set_quality(f"Данные устарели. {reason}")
        elif quality == "bad":
            self._widget.set_quality("Нет данных.")
        else:
            self._widget.set_quality("")

    # ------------------------------------------------------------------ #
    # Describe — лимиты + gating
    # ------------------------------------------------------------------ #

    def _on_describe(self, data: dict) -> None:
        """Обработчик describe: установить лимиты частоты и gating."""
        if not data:
            self._widget.set_controls_enabled(True, "")
            return
        # Лимиты, каждая граница отдельно: protocol_meta.cmd_freq -> entry.params рецепта -> 0 / 50
        cmd_freq_meta = (data.get("protocol_meta") or {}).get("cmd_freq") or {}
        params = (data.get("entry") or {}).get("params") or {}
        freq_min = float(cmd_freq_meta.get("min", params.get("freq_min_hz", 0)))
        freq_max = float(cmd_freq_meta.get("max", params.get("freq_max_hz", 50)))
        if freq_max > 0:
            self._widget.set_freq_range(freq_min, freq_max)

        # Gating: если носитель-робот в режиме draw
        carrier = data.get("carrier") or {}
        mode = carrier.get("mode", "")
        if mode == "draw":
            self._widget.set_controls_enabled(
                False,
                "ПЧ недоступен в режиме DRAW: робот не обслуживает команды ПЧ "
                "во время рисования (ограничение протокола).",
            )
        else:
            self._widget.set_controls_enabled(True, "")

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def _on_run(self, freq: float, reverse: bool) -> None:
        if not self._device_id:
            return
        direction = "реверс" if reverse else "вперёд"
        self._widget.set_status(f"ПЧ: пуск {direction} {freq:.2f} Гц…")
        self._widget.set_refusal("")
        self._presenter.vfd_run(self._device_id, freq, reverse, on_result=self._reply_handler())

    def _on_set_freq(self, freq: float) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"ПЧ: смена частоты {freq:.2f} Гц…")
        self._widget.set_refusal("")
        self._presenter.vfd_set_freq(self._device_id, freq, on_result=self._reply_handler())

    def _on_stop(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("ПЧ: стоп…")
        self._widget.set_refusal("")
        self._presenter.vfd_stop(self._device_id, on_result=self._reply_handler())

    def _on_reset(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("ПЧ: сброс аварии…")
        self._widget.set_refusal("")
        self._presenter.vfd_reset_fault(self._device_id)

    def _reply_handler(self) -> Callable[[Any], None]:
        """Колбэк ответа команды, привязанный к устройству, выбранному при отправке."""
        device_id = self._device_id

        def handle(response: Any) -> None:
            if device_id == self._device_id:
                self._show_reply(response)

        return handle

    def _show_reply(self, response: Any) -> None:
        """Отказ и отложенный «Стоп» — в метку отказа. Успех и ``{}`` (нет sender) метку не трогают:
        она очищена при нажатии, а поздний успех прежней команды не должен стереть текст следующей.
        """
        envelope = response if isinstance(response, dict) else {}
        reply = unwrap_reply(envelope)
        refused = (
            envelope.get("success") is False
            or reply.get("success") is False
            or ("status" in reply and reply["status"] != "ok")
        )
        if refused:
            self._widget.set_refusal(str(reply.get("message") or _REFUSAL_DEFAULT))
        elif reply.get("deferred"):
            self._widget.set_refusal(str(reply.get("message") or ""))

    def _on_refresh(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("Запрос статуса…")
        self._presenter.vfd_get_status(self._device_id, self._on_vfd_status_response)

    def _on_vfd_status_response(self, data: dict) -> None:
        """Обработчик ответа vfd_get_status (pull)."""
        vfd = data.get("vfd") or data
        if isinstance(vfd, dict) and ("running" in vfd or "out_freq_hz" in vfd):
            self._apply_vfd_status(vfd)
        else:
            self._widget.set_status("ПЧ: нет данных.")


def _num(value: Any, spec: str) -> str:
    """Число статуса в формате ``spec``; нет значения — «—», а не ноль."""
    return "—" if value is None else format(float(value), spec)


def _conn_text(value: Any) -> str:
    """Формат conn-значения для отображения."""
    if isinstance(value, dict):
        return str(value.get("conn", "?"))
    return str(value)


def build_vfd_controls(
    *,
    runtime: Any,
    request_runner: Any,
    bindings: Any = None,
) -> tuple[VfdControlWidget, VfdWidgetController, VfdPresenter]:
    """Собрать виджет + presenter + controller с зависимостями."""
    widget = VfdControlWidget()
    presenter = VfdPresenter(
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    controller = VfdWidgetController(
        widget,
        presenter,
        bindings=bindings,
    )
    return widget, controller, presenter
