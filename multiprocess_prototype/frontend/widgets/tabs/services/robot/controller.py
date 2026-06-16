# -*- coding: utf-8 -*-
"""RobotWidgetController — проводка RobotControlWidget <-> RobotPresenter.

Фаза 4 device-hub: ПЧ-обработчики убраны (отдельная вкладка «ПЧ»). Все
команды передают device_id выбранного робота. Телеметрия — bindings на
``devices.state.<id>.status`` (push); кнопка «Обновить» — форс-запрос
``robot_get_telemetry``.

UX-ограничения:
- CVT/DRAW активен только при free=1;
- Gating CVT/DRAW по free сохранён.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QTimer

from .presenter import RobotPresenter
from .widget import RobotControlWidget

# н5 ревью Fable (ADR-PH-001): порог устаревания данных hub.
# Если time.time() - ts > _STALE_THRESHOLD_S, данные считаются stale
# независимо от quality-поля (hub мог упасть и quality «замёрз»).
_STALE_THRESHOLD_S = 3.0


class RobotWidgetController:
    """Связывает виджет робота с presenter (команды + статусы)."""

    def __init__(
        self,
        widget: RobotControlWidget,
        presenter: RobotPresenter,
        *,
        bindings: Any = None,
    ) -> None:
        self._widget = widget
        self._presenter = presenter
        self._bindings = bindings
        self._device_id: str | None = None
        self._status_handles: list[Any] = []

        # н5 ревью Fable: QTimer для периодической проверки устаревания
        # данных. Если hub упал — пуши прекращаются, но индикатор
        # должен перейти в stale через _STALE_THRESHOLD_S.
        self._last_status_ts: float | None = None
        self._stale_timer = QTimer()
        self._stale_timer.setInterval(2000)  # 2 с
        self._stale_timer.timeout.connect(self._check_stale)

        self._connect()

    def _connect(self) -> None:
        w = self._widget
        w.refresh_requested.connect(self._on_refresh)
        w.send_job_requested.connect(self._on_send_job)
        w.stop_requested.connect(self._on_stop)
        w.mode_change_requested.connect(self._on_mode)
        w.servo_requested.connect(self._on_servo)
        w.manual_mode_toggled.connect(self._on_manual)
        w.jog_requested.connect(self._on_jog)
        w.jog_abort_requested.connect(self._on_jog_abort)

        w.draw_circle_requested.connect(self._on_draw_circle)
        w.draw_square_requested.connect(self._on_draw_square)
        w.draw_abort_requested.connect(self._on_draw_abort)
        w.pen_apply_requested.connect(self._on_pen)
        w.draw_speed_requested.connect(self._on_draw_speed)
        w.overlap_requested.connect(self._on_overlap)
        w.camera_freeze_requested.connect(self._on_camera_freeze)
        w.camera_resume_requested.connect(self._on_camera_resume)
        w.send_to_robot_requested.connect(self._on_send_to_robot)

    # ------------------------------------------------------------------ #
    # Смена устройства
    # ------------------------------------------------------------------ #

    def set_device(self, device_id: str | None) -> None:
        """Переключить на другое устройство: перепривязать bindings."""
        self._unbind_state()
        self._device_id = device_id
        self._last_status_ts = None
        if not device_id:
            self._stale_timer.stop()
            self._widget.set_status("Робот: устройство не выбрано.")
            self._widget.set_mode_switch_enabled(False)
            return
        self._bind_state(device_id)
        self._stale_timer.start()
        self._widget.set_status(f"Робот: выбрано устройство {device_id}.")

    # ------------------------------------------------------------------ #
    # Bindings
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
            self._widget.set_status(
                f"Нет связи с hub (данные устарели на {age:.1f} с). Процесс devices может быть недоступен."
            )
            self._widget.set_mode_switch_enabled(False)

    def _unbind_state(self) -> None:
        if self._bindings is not None:
            for h in self._status_handles:
                try:
                    self._bindings.unbind(h)
                except Exception:
                    pass
        self._status_handles.clear()

    def _bind_state(self, device_id: str) -> None:
        """Привязать виджет к devices.state.<id>.status (push-телеметрия)."""
        self._unbind_state()
        if self._bindings is None:
            return
        base = f"devices.state.{device_id}"
        if hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(
                f"{base}.status",
                self._on_telemetry_push,
                owner=self._widget,
            )

    def _on_telemetry_push(self, _path: str, value: Any) -> None:
        """Push-телеметрия из state-дерева."""
        if isinstance(value, dict):
            # н5: запомнить время последнего пуша для stale-timer
            self._last_status_ts = time.time()
            self._apply_telemetry(value)

    def _apply_telemetry(self, data: dict) -> None:
        """Обновить виджет по snapshot телеметрии робота."""
        # н5/ADR-PH-001: проверка возраста ts — hub мог упасть
        ts = data.get("ts")
        if ts is not None:
            age = time.time() - float(ts)
            if age > _STALE_THRESHOLD_S:
                self._widget.set_status(
                    f"Нет связи с hub (данные устарели на {age:.1f} с). Процесс devices может быть недоступен."
                )
                self._widget.set_mode_switch_enabled(False)
                return

        telemetry = data.get("telemetry")
        if isinstance(telemetry, dict):
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
            bool((telemetry or {}).get("servo", False)),
            int(data.get("encoder", 0)),
            int(data.get("queue_len", 0)),
        )
        # Lua применяет режим раз за итерацию Motion — переключать только в idle
        self._widget.set_mode_switch_enabled(free)

    # ------------------------------------------------------------------ #
    # Робот
    # ------------------------------------------------------------------ #

    def _on_send_job(self, x: float, y: float, z: float = 0.0) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"Тест-job X={x:.1f} Y={y:.1f} Z={z:.1f} отправлен.")
        self._presenter.send_test_job(self._device_id, x, y, z)

    def _on_stop(self, mode: int) -> None:
        if not self._device_id:
            return
        labels = {1: "СТОП: домой, в цикле", 2: "СТОП: домой, выход", 3: "СТОП: на месте"}
        self._widget.set_status(labels.get(mode, "СТОП"))
        self._presenter.abort(self._device_id, mode)

    def _on_mode(self, mode: str) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"Режим {mode.upper()}.")
        self._presenter.set_mode(self._device_id, mode)

    def _on_servo(self, on: bool) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"Серво {'ON' if on else 'OFF'}.")
        self._presenter.set_servo(self._device_id, on)

    def _on_manual(self, on: bool) -> None:
        if not self._device_id:
            return
        self._widget.set_status("Ручной режим: авто-подача на паузе." if on else "Авто-подача возобновлена.")
        self._presenter.set_manual_mode(self._device_id, on)

    def _on_jog(self, dx: float, dy: float, spd: int, absolute: bool) -> None:
        if not self._device_id:
            return
        kind = "абс" if absolute else "отн"
        self._widget.set_status(f"Jog dX={dx:.1f} dY={dy:.1f} @ {spd}% ({kind}).")
        self._presenter.jog(self._device_id, dx, dy, int(spd), bool(absolute))

    def _on_jog_abort(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("Jog: стоп.")
        self._presenter.jog_abort(self._device_id)

    # ------------------------------------------------------------------ #
    # Рисование
    # ------------------------------------------------------------------ #

    def _on_draw_circle(self, cx: float, cy: float, r: float, z: float) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"Круг ({cx:.1f},{cy:.1f}) R={r:.1f} поставлен в очередь.")
        self._presenter.draw_circle(self._device_id, cx, cy, r, z)

    def _on_draw_square(self, x1: float, y1: float, x2: float, y2: float, z: float) -> None:
        if not self._device_id:
            return
        self._widget.set_status("Квадрат поставлен в очередь.")
        self._presenter.draw_square(self._device_id, x1, y1, x2, y2, z)

    def _on_draw_abort(self) -> None:
        if not self._device_id:
            return
        self._widget.set_status("Рисование прервано.")
        self._presenter.abort_draw(self._device_id)

    def _on_pen(self, down: float, up: float) -> None:
        if not self._device_id:
            return
        self._widget.set_status(f"Перо: down={down:.1f} up={up:.1f}.")
        self._presenter.set_pen(self._device_id, down, up)

    def _on_draw_speed(self, pct: int) -> None:
        if not self._device_id:
            return
        self._presenter.set_draw_speed(self._device_id, pct)

    def _on_overlap(self, mm: float) -> None:
        if not self._device_id:
            return
        self._presenter.set_overlap(self._device_id, mm)

    # ------------------------------------------------------------------ #
    # Портрет (рецепт webcam_sketch): заморозка / возобновление / отправка
    # ------------------------------------------------------------------ #

    def _on_camera_freeze(self, process_name: str) -> None:
        proc = process_name or "camera_0"
        self._widget.set_status(f"Заморозка кадра ({proc})…")
        self._presenter.freeze_camera(proc, self._on_camera_freeze_result)

    def _on_camera_freeze_result(self, data: dict) -> None:
        if isinstance(data, dict) and data.get("status") == "ok":
            self._widget.set_status("Кадр заморожен — подстрой параметры и жми «Отправить роботу».")
        else:
            msg = data.get("message", "процесс камеры недоступен?") if isinstance(data, dict) else "?"
            self._widget.set_status(f"Не удалось заморозить кадр ({msg}).")

    def _on_camera_resume(self, process_name: str) -> None:
        proc = process_name or "camera_0"
        self._widget.set_status(f"Возобновление камеры ({proc})…")
        self._presenter.resume_camera(proc, lambda d: self._widget.set_status("Камера возобновлена."))

    def _on_send_to_robot(self, process_name: str) -> None:
        proc = process_name or "points"
        self._widget.set_status(f"Отправка точек роботу ({proc})…")
        self._presenter.send_to_robot(proc, self._on_send_result)

    def _on_send_result(self, data: dict) -> None:
        if isinstance(data, dict) and (data.get("armed") or data.get("status") == "ok"):
            self._widget.set_status("Точки отправлены — робот рисует и остановится по завершении.")
        else:
            self._widget.set_status("Не удалось отправить точки (процесс points недоступен?).")

    # ------------------------------------------------------------------ #
    # Форс-запрос
    # ------------------------------------------------------------------ #

    def _on_refresh(self) -> None:
        """Кнопка «Обновить»: форс-запрос телеметрии + рисования."""
        if not self._device_id:
            self._widget.set_status("Робот: устройство не выбрано.")
            return
        self._widget.set_status("Опрос робота…")
        self._presenter.get_telemetry(self._device_id, self._on_telemetry_response)
        self._presenter.get_draw_progress(self._device_id, self._on_draw_progress)

    def _on_telemetry_response(self, data: dict) -> None:
        """Обработчик ответа get_telemetry (pull)."""
        if not data or not data.get("telemetry"):
            self._widget.set_status("Робот не отвечает (телеметрия пуста).")
            self._widget.set_mode_switch_enabled(False)
            return
        self._apply_telemetry(data)

    def _on_draw_progress(self, data: dict) -> None:
        """Обработчик ответа draw_progress."""
        state = data.get("state", "—")
        busy = data.get("busy")
        point = data.get("progress_point", 0)
        total = data.get("total_points", 0)
        queued = data.get("queued", 0)
        self._widget.set_draw_status(f"Рисование: {state}  busy={busy}  точка {point}/{total}  в очереди {queued}")


def build_robot_controls(
    *,
    runtime: Any,
    request_runner: Any,
    bindings: Any = None,
) -> tuple[RobotControlWidget, RobotWidgetController, RobotPresenter]:
    """Собрать виджет + presenter + controller с зависимостями."""
    widget = RobotControlWidget()
    presenter = RobotPresenter(
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    controller = RobotWidgetController(
        widget,
        presenter,
        bindings=bindings,
    )
    return widget, controller, presenter
