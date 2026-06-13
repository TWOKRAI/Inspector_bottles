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
        self._connect()

    def _connect(self) -> None:
        w = self._widget
        w.begin_requested.connect(self._on_begin)
        w.capture_requested.connect(self._on_capture)
        w.set_point_requested.connect(self._on_set_point)
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
        self._widget.set_status(f"Робот «{device_id}» выбран. Нажмите «Начать сессию», затем «Снять кадр».")
        # Предварительно подписаться на прогресс для camera_id по умолчанию из поля.
        self._bind_progress(self._widget.camera_id)

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
        self._widget.set_status(f"Наведение робота на точку {index + 1}…")
        self._presenter.set_robot_point(index)

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
