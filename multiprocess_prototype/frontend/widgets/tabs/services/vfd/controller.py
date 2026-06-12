# -*- coding: utf-8 -*-
"""VfdWidgetController — проводка VfdControlWidget <-> VfdPresenter.

Связывает сигналы виджета с командами presenter; bindings на state-пути
devices.state.<id>.{status,conn,last_error}; перепривязка при смене
устройства в комбо. UX-gating: DRAW-режим робота-носителя.
comm_errors — с дельтой за период (перенесено из robot/controller).
"""

from __future__ import annotations

import time
from typing import Any

from .presenter import VfdPresenter
from .widget import VfdControlWidget

# н5 ревью Fable (ADR-PH-001): порог устаревания данных hub.
# Если time.time() - ts > _STALE_THRESHOLD_S, данные считаются stale
# независимо от quality-поля (hub мог упасть и quality «замёрз»).
_STALE_THRESHOLD_S = 3.0


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
        self._device_id = device_id
        self._last_comm_errors = None
        if not device_id:
            self._widget.set_status("ПЧ: устройство не выбрано.")
            self._widget.set_controls_enabled(False, "Выберите устройство.")
            return
        self._bind_state(device_id)
        # Запросить describe для лимитов частоты и gating
        self._presenter.device_describe(device_id, self._on_describe)

    # ------------------------------------------------------------------ #
    # Bindings на state-пути
    # ------------------------------------------------------------------ #

    def _unbind_state(self) -> None:
        if self._bindings is not None:
            for h in self._status_handles:
                try:
                    self._bindings.unbind(h)
                except Exception:
                    pass
        self._status_handles.clear()

    def _bind_state(self, device_id: str) -> None:
        """Привязать виджет к devices.state.<id>.{status,conn,last_error}."""
        self._unbind_state()
        if self._bindings is None:
            return
        base = f"devices.state.{device_id}"

        # Статус ПЧ (push) — вызываем _on_status_push
        if hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(
                f"{base}.status",
                self._on_status_push,
                owner=self._widget,
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
        self._apply_vfd_status(value)

    def _apply_vfd_status(self, vfd: dict) -> None:
        """Обновить виджет по snapshot статуса ПЧ."""
        comm = int(vfd.get("comm_errors") or 0)
        delta = ""
        if self._last_comm_errors is not None:
            delta = f" (+{max(0, comm - self._last_comm_errors)})"
        self._last_comm_errors = comm

        running = "RUN" if vfd.get("running") else "STOP"
        fault = vfd.get("fault") or 0
        fault_text = f"  АВАРИЯ=0x{int(fault):04X}" if fault else ""
        hb = vfd.get("heartbeat", "?")

        self._widget.set_status(
            f"[{running}] f={float(vfd.get('out_freq_hz', 0)):.2f} Гц  "
            f"I={float(vfd.get('current_a', 0)):.1f} А  "
            f"Udc={float(vfd.get('dcbus_v', 0)):.1f} В  "
            f"hb={hb}  rsErr={comm}{delta}{fault_text}"
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
        # Лимиты из protocol_meta
        meta = data.get("protocol_meta") or {}
        cmd_freq_meta = meta.get("cmd_freq") or {}
        freq_min = float(cmd_freq_meta.get("min", 0))
        freq_max = float(cmd_freq_meta.get("max", 50))
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
        self._presenter.vfd_run(self._device_id, freq, reverse)

    def _on_set_freq(self, freq: float) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"ПЧ: смена частоты {freq:.2f} Гц…")
        self._presenter.vfd_set_freq(self._device_id, freq)

    def _on_stop(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("ПЧ: стоп…")
        self._presenter.vfd_stop(self._device_id)

    def _on_reset(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("ПЧ: сброс аварии…")
        self._presenter.vfd_reset_fault(self._device_id)

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
