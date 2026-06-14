# -*- coding: utf-8 -*-
"""CalibrationController — проводка CalibrationWizardWidget ↔ CalibrationPresenter.

- сигналы виджета → команды presenter (robot_id = выбранное устройство);
- подписка на ``calibration.state.<camera_id>.progress`` (push) → widget.set_progress;
- резолв target-процесса (где живёт плагин camera_robot_calibration) из активного рецепта.
"""

from __future__ import annotations

from typing import Any

from .presenter import CalibrationPresenter
from .widget import CalibrationWizardWidget


def resolve_calibration_process(recipes: Any, default: str = "cal") -> str:
    """Имя процесса с плагином camera_robot_calibration в активном рецепте (или default)."""
    try:
        if recipes is None:
            return default
        slug = recipes.get_active()
        if not slug:
            return default
        raw = recipes.read_raw(slug) or {}
        blueprint = raw.get("blueprint") or {}
        for proc in blueprint.get("processes", []):
            for plug in proc.get("plugins", []):
                if plug.get("plugin_name") == "camera_robot_calibration":
                    return proc.get("process_name", default)
    except Exception:
        pass
    return default


class CalibrationController:
    """Связывает виджет визарда с presenter + подписка на прогресс калибровки."""

    def __init__(
        self,
        widget: CalibrationWizardWidget,
        presenter: CalibrationPresenter,
        *,
        bindings: Any = None,
    ) -> None:
        self._widget = widget
        self._presenter = presenter
        self._bindings = bindings
        self._robot_id: str | None = None
        self._camera_id: str | None = None
        self._progress_owner_path: str | None = None
        # Push-телеметрия робота (как ручная вкладка): кэш текущих координат/энкодера.
        self._robot_tlm_id: str | None = None
        self._robot_xy: tuple[float, float] | None = None
        self._robot_enc: int | None = None
        # Последний снапшот прогресса — для live_px при записи точки.
        self._last_snapshot: dict = {}
        self._connect()

    def _connect(self) -> None:
        w = self._widget
        w.begin_requested.connect(self._on_begin)
        w.capture_requested.connect(self._on_capture)
        w.set_point_requested.connect(self._on_set_point)
        w.point_px_edited.connect(self._on_point_px_edited)
        w.point_robot_edited.connect(self._on_point_robot_edited)
        w.belt_run_requested.connect(self._on_belt_run)
        w.belt_stop_requested.connect(self._on_belt_stop)
        w.encoder_scale_requested.connect(self._on_encoder_scale)
        w.compute_requested.connect(self._presenter.compute)
        w.save_requested.connect(self._presenter.save)
        w.reset_requested.connect(self._presenter.reset)

    # ------------------------------------------------------------------ #
    # Смена устройства (робота)
    # ------------------------------------------------------------------ #

    def set_device(self, device_id: str | None) -> None:
        self._robot_id = device_id
        if not device_id:
            self._widget.set_controls_enabled(False, "Калибровка: выберите робота.")
            return
        self._widget.set_controls_enabled(True)
        # Подписка на живую телеметрию робота (тот же push, что в «Ручном управлении»).
        self._bind_robot_telemetry(device_id)
        cam = self._widget.camera_id
        vfd = self._widget.vfd_id
        self._bind_progress(cam)
        self._widget.set_status(
            f"Робот «{device_id}». Наведи плату (live 5/5), затем жми «Точка N» по номерам на кадре."
        )
        # Авто-старт сессии (кнопки «Начать сессию» больше нет).
        self._presenter.begin(cam, device_id, vfd)

    def _bind_robot_telemetry(self, device_id: str) -> None:
        """Подписаться на devices.state.<id>.status → кэш x/y/encoder робота (push)."""
        if self._bindings is None or not device_id or device_id == self._robot_tlm_id:
            return
        self._robot_tlm_id = device_id
        path = f"devices.state.{device_id}.status"
        if hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(path, self._on_robot_status, owner=self._widget)

    def _on_robot_status(self, _path: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        tel = value.get("telemetry") or {}
        x = tel.get("x_mm")
        y = tel.get("y_mm")
        enc = value.get("encoder")
        if x is None or y is None:
            return
        self._robot_xy = (float(x), float(y))
        self._robot_enc = int(enc) if enc is not None else None
        self._widget.set_robot_live(float(x), float(y), self._robot_enc)

    def unbind(self) -> None:
        self._unbind_progress()

    # ------------------------------------------------------------------ #
    # Подписка на прогресс
    # ------------------------------------------------------------------ #

    def _bind_progress(self, camera_id: str) -> None:
        if self._bindings is None or not camera_id:
            return
        if camera_id == self._camera_id:
            return
        self._unbind_progress()
        self._camera_id = camera_id
        path = f"calibration.state.{camera_id}.progress"
        if hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(path, self._on_progress_push, owner=self._widget)
            self._progress_owner_path = path

    def _unbind_progress(self) -> None:
        # bind_fanout привязан к owner=widget; явного unbind по owner здесь нет —
        # повторный bind на тот же owner/path фреймворк дедуплицирует. Сбрасываем метку.
        self._camera_id = None
        self._progress_owner_path = None

    def _on_progress_push(self, _path: str, value: Any) -> None:
        if isinstance(value, dict):
            self._last_snapshot = value
        self._widget.set_progress(value)

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def _on_begin(self, camera_id: str, vfd_id: str) -> None:
        if not self._robot_id:
            self._widget.set_status("Сначала выберите робота.")
            return
        self._bind_progress(camera_id)
        self._widget.set_status(f"Старт сессии: camera={camera_id}, robot={self._robot_id}, vfd={vfd_id}…")
        self._presenter.begin(camera_id, self._robot_id, vfd_id)

    def _on_capture(self) -> None:
        self._widget.set_status("Снятие кадра (ожидаем 5 точек)…")
        self._presenter.capture_image()

    def _on_set_point(self, index: int) -> None:
        """«Точка N»: записать px (live-детекция) + координаты робота (push) + энкодер.

        Не использует сломанный pull `cal_set_robot_point` — берём всё с GUI-стороны
        и пишем через `cal_set_point` (плагин просто сохраняет, без IPC к роботу).
        """
        if self._robot_xy is None:
            self._widget.set_status("Нет телеметрии робота — проверь подключение (вкладка «Ручное управление»).")
            return
        live_px = (self._last_snapshot or {}).get("live_px") or []
        px = live_px[index] if index < len(live_px) and live_px[index] else None
        x, y = self._robot_xy
        self._presenter.set_point(index, px=px, mm=[x, y], enc=self._robot_enc)
        if px is None:
            self._widget.set_status(
                f"Точка {index + 1}: робот ({x:.1f}, {y:.1f}) записан, но px НЕ записан "
                f"(нужно live 5/5 — наведи плату)."
            )
        else:
            self._widget.set_status(f"Точка {index + 1}: px={px}, робот ({x:.1f}, {y:.1f}), enc={self._robot_enc}")

    def _on_point_px_edited(self, index: int, x: float, y: float) -> None:
        self._widget.set_status(f"Точка {index + 1}: ручная правка px ({x:.0f}, {y:.0f})")
        self._presenter.set_point(int(index), px=[x, y])

    def _on_point_robot_edited(self, index: int, x: float, y: float) -> None:
        self._widget.set_status(f"Точка {index + 1}: ручная правка робот ({x:.1f}, {y:.1f})")
        self._presenter.set_point(int(index), mm=[x, y])

    def _on_belt_run(self, freq: float) -> None:
        self._widget.set_status(f"Лента: пуск {freq:.2f} Гц…")
        self._presenter.belt_run(freq)

    def _on_belt_stop(self) -> None:
        self._widget.set_status("Лента: стоп…")
        self._presenter.belt_stop()

    def _on_encoder_scale(self, ref_index: int) -> None:
        self._widget.set_status(f"Снятие масштаба ленты (репер — точка {ref_index + 1})…")
        self._presenter.encoder_scale(ref_index)


def build_calibration_controls(
    *,
    runtime: Any,
    request_runner: Any,
    bindings: Any = None,
    target_process: str = "cal",
) -> tuple[CalibrationWizardWidget, CalibrationController, CalibrationPresenter]:
    """Собрать виджет + presenter + controller визарда калибровки."""
    widget = CalibrationWizardWidget()
    presenter = CalibrationPresenter(
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
        target_process=target_process,
    )
    controller = CalibrationController(widget, presenter, bindings=bindings)
    return widget, controller, presenter
