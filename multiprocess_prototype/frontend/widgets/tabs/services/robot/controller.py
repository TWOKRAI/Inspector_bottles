# -*- coding: utf-8 -*-
"""RobotWidgetController — проводка RobotControlWidget ↔ RobotPresenter.

Связывает сигналы виджета с командами presenter; по refresh опрашивает
телеметрию/ПЧ/рисование (request/response) и применяет UX-ограничения:
- CVT/DRAW активен только при free=1;
- VFD-кнопки дизейблятся в DRAW-режиме (до Lua-улучшения №2);
- comm_errors показывается с дельтой за период (RS-485 медленный, абсолют
  сам по себе не информативен);
- «связь жива» — по успешности чтений, не по TLM-heartbeat.
"""

from __future__ import annotations

from typing import Any

from .presenter import RobotPresenter
from .widget import RobotControlWidget


class RobotWidgetController:
    """Связывает виджет робота с presenter (команды + статусы)."""

    def __init__(self, widget: RobotControlWidget, presenter: RobotPresenter) -> None:
        self._widget = widget
        self._presenter = presenter
        self._last_comm_errors: int | None = None
        self._connect()
        self.refresh_status()

    def _connect(self) -> None:
        w = self._widget
        w.refresh_requested.connect(self.refresh_status)
        w.send_job_requested.connect(self._on_send_job)
        w.stop_requested.connect(self._on_stop)
        w.mode_change_requested.connect(self._on_mode)
        w.servo_requested.connect(self._on_servo)
        w.manual_mode_toggled.connect(self._on_manual)

        w.draw_circle_requested.connect(self._on_draw_circle)
        w.draw_square_requested.connect(self._on_draw_square)
        w.draw_abort_requested.connect(self._on_draw_abort)
        w.pen_apply_requested.connect(self._on_pen)
        w.draw_speed_requested.connect(self._presenter.set_draw_speed)
        w.overlap_requested.connect(self._presenter.set_overlap)

        w.vfd_run_requested.connect(self._on_vfd_run)
        w.vfd_set_freq_requested.connect(self._on_vfd_freq)
        w.vfd_stop_requested.connect(self._on_vfd_stop)
        w.vfd_reset_requested.connect(self._on_vfd_reset)

    # ------------------------------------------------------------------ #
    # Робот
    # ------------------------------------------------------------------ #

    def _on_send_job(self, x: float, y: float) -> None:
        ok = self._presenter.send_test_job(x, y)
        self._widget.set_status(f"Тест-job X={x:.1f} Y={y:.1f} отправлен." if ok else self._no_live_hint())

    def _on_stop(self, mode: int) -> None:
        ok = self._presenter.abort(mode)
        labels = {1: "СТОП: домой, в цикле", 2: "СТОП: домой, выход", 3: "СТОП: на месте"}
        self._widget.set_status(labels.get(mode, "СТОП") if ok else self._no_live_hint())

    def _on_mode(self, mode: str) -> None:
        ok = self._presenter.set_mode(mode)
        if ok:
            self._widget.set_status(f"Режим {mode.upper()}.")
        else:
            self._widget.set_status(self._no_live_hint())
        self._apply_vfd_gating(mode)

    def _on_servo(self, on: bool) -> None:
        ok = self._presenter.set_servo(on)
        self._widget.set_status(f"Серво {'ON' if on else 'OFF'}." if ok else self._no_live_hint())

    def _on_manual(self, on: bool) -> None:
        ok = self._presenter.set_manual_mode(on)
        self._widget.set_status(
            ("Ручной режим: авто-подача на паузе." if on else "Авто-подача возобновлена.")
            if ok
            else self._no_live_hint()
        )

    # ------------------------------------------------------------------ #
    # Рисование
    # ------------------------------------------------------------------ #

    def _on_draw_circle(self, cx: float, cy: float, r: float, z: float) -> None:
        ok = self._presenter.draw_circle(cx, cy, r, z)
        text = f"Круг ({cx:.1f},{cy:.1f}) R={r:.1f} поставлен в очередь."
        self._widget.set_status(text if ok else self._no_live_hint())

    def _on_draw_square(self, x1: float, y1: float, x2: float, y2: float, z: float) -> None:
        ok = self._presenter.draw_square(x1, y1, x2, y2, z)
        self._widget.set_status("Квадрат поставлен в очередь." if ok else self._no_live_hint())

    def _on_draw_abort(self) -> None:
        ok = self._presenter.abort_draw()
        self._widget.set_status("Рисование прервано." if ok else self._no_live_hint())

    def _on_pen(self, down: float, up: float) -> None:
        ok = self._presenter.set_pen(down, up)
        self._widget.set_status(f"Перо: down={down:.1f} up={up:.1f}." if ok else self._no_live_hint())

    # ------------------------------------------------------------------ #
    # ПЧ
    # ------------------------------------------------------------------ #

    def _on_vfd_run(self, freq: float, reverse: bool) -> None:
        ok = self._presenter.vfd_run(freq, reverse)
        direction = "реверс" if reverse else "вперёд"
        self._widget.set_status(f"ПЧ: пуск {direction} {freq:.2f} Гц." if ok else self._no_live_hint())

    def _on_vfd_freq(self, freq: float) -> None:
        ok = self._presenter.vfd_set_freq(freq)
        self._widget.set_status(f"ПЧ: частота {freq:.2f} Гц." if ok else self._no_live_hint())

    def _on_vfd_stop(self) -> None:
        ok = self._presenter.vfd_stop()
        self._widget.set_status("ПЧ: стоп." if ok else self._no_live_hint())

    def _on_vfd_reset(self) -> None:
        ok = self._presenter.vfd_reset_fault()
        self._widget.set_status("ПЧ: сброс аварии." if ok else self._no_live_hint())

    # ------------------------------------------------------------------ #
    # Статусы (request/response)
    # ------------------------------------------------------------------ #

    def refresh_status(self) -> None:
        """Опросить телеметрию робота, статус ПЧ и прогресс рисования."""
        if not self._presenter.is_live:
            self._widget.set_status(
                "Нода робота не запущена. Активируйте рецепт с плагином robot_io "
                "(robot_io + vfd_control + robot_draw в одном процессе)."
            )
            self._widget.set_mode_switch_enabled(False)
            self._widget.set_vfd_enabled(False, "ПЧ недоступен: нет ноды робота.")
            return
        self._widget.set_status("Опрос ноды робота…")
        self._presenter.get_telemetry(self._on_telemetry)
        self._presenter.get_vfd_status(self._on_vfd_status)
        self._presenter.get_draw_progress(self._on_draw_progress)

    def _on_telemetry(self, data: dict) -> None:
        telemetry = data.get("telemetry")
        if not isinstance(telemetry, dict):
            # связь жива = успешность чтений: пустой ответ -> робот не отвечает
            self._widget.set_status("Робот не отвечает (телеметрия пуста).")
            self._widget.set_mode_switch_enabled(False)
            return
        self._widget.set_status("Связь с роботом активна.")
        self._widget.set_telemetry(
            float(telemetry.get("x_mm", 0)),
            float(telemetry.get("y_mm", 0)),
            float(telemetry.get("z_mm", 0)),
            float(telemetry.get("rz_deg", 0)),
        )
        free = bool(data.get("free", False))
        self._widget.set_flags(
            free,
            bool(telemetry.get("servo", False)),
            int(data.get("encoder", 0)),
            int(data.get("queue_len", 0)),
        )
        # Lua применяет режим раз за итерацию Motion — переключать только в idle
        self._widget.set_mode_switch_enabled(free)
        self._apply_vfd_gating(self._widget.current_mode())

    def _on_vfd_status(self, data: dict) -> None:
        vfd = data.get("vfd")
        if not isinstance(vfd, dict):
            self._widget.set_vfd_status("ПЧ: нет данных (мост недоступен?).")
            return
        comm = int(vfd.get("comm_errors") or 0)
        delta = "" if self._last_comm_errors is None else f" (+{max(0, comm - self._last_comm_errors)})"
        self._last_comm_errors = comm
        running = "RUN" if vfd.get("running") else "STOP"
        fault = vfd.get("fault") or 0
        fault_text = f"  АВАРИЯ=0x{int(fault):04X}" if fault else ""
        alive = "жив" if data.get("bridge_alive") else "ЗАМОРОЖЕН"
        self._widget.set_vfd_status(
            f"[{running}] f={float(vfd.get('out_freq_hz', 0)):.2f} Гц  I={float(vfd.get('current_a', 0)):.1f} А  "
            f"Udc={float(vfd.get('dcbus_v', 0)):.1f} В  hb={vfd.get('heartbeat')} ({alive})  "
            f"rsErr={comm}{delta}{fault_text}"
        )

    def _on_draw_progress(self, data: dict) -> None:
        state = data.get("state", "—")
        busy = data.get("busy")
        point = data.get("progress_point", 0)
        total = data.get("total_points", 0)
        queued = data.get("queued", 0)
        self._widget.set_draw_status(f"Рисование: {state}  busy={busy}  точка {point}/{total}  в очереди {queued}")

    def _no_live_hint(self) -> str:
        return (
            "Команда не отправлена: нет запущенной ноды робота. Активируйте рецепт "
            "с robot_io (+ vfd_control / robot_draw в том же процессе)."
        )

    def _apply_vfd_gating(self, mode: str) -> None:
        """VFD-кнопки в DRAW дизейблятся: Lua не обслуживает VFD_FLAG вне CVT-idle."""
        if mode == "draw":
            self._widget.set_vfd_enabled(
                False,
                "ПЧ недоступен в режиме DRAW: робот не обслуживает команды ПЧ во время "
                "рисования (ограничение протокола; переключитесь в CVT).",
            )
        else:
            self._widget.set_vfd_enabled(True, "")


def build_robot_controls(
    *,
    services: Any,
    runtime: Any,
    request_runner: Any,
) -> tuple[RobotControlWidget, RobotWidgetController]:
    """Собрать виджет + presenter + controller с зависимостями из services/runtime."""
    widget = RobotControlWidget()
    presenter = RobotPresenter(
        bridge=getattr(runtime, "topology_bridge", None),
        topology=getattr(services, "topology", None),
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    controller = RobotWidgetController(widget, presenter)
    return widget, controller
