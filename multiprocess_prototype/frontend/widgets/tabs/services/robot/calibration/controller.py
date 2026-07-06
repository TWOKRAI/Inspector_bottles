# -*- coding: utf-8 -*-
"""CalibrationController — проводка CalibrationWizardWidget ↔ CalibrationPresenter.

- сигналы виджета → команды presenter (robot_id = выбранное устройство);
- подписка на ``calibration.state.<camera_id>.progress`` (push) → widget.set_progress;
- резолв target-процесса (где живёт плагин camera_robot_calibration) из активного рецепта.
"""

from __future__ import annotations

from typing import Any

from ..presenter import RobotPresenter
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
        robot_presenter: Any = None,
    ) -> None:
        self._widget = widget
        self._presenter = presenter
        self._bindings = bindings
        # Презентер робота (target=devices) для pull `robot_get_telemetry` ПО ЗАПРОСУ.
        # Push devices.state.<id>.status до GUI в этом рецепте не доходит, поэтому
        # координаты робота берём свежим опросом в момент нажатия «Точка N» / выбора робота.
        self._robot_presenter = robot_presenter
        self._robot_id: str | None = None
        self._camera_id: str | None = None
        self._progress_owner_path: str | None = None
        # Хэндл fanout-подписки на прогресс (bind_fanout) — для явной отписки.
        self._progress_handle: Any = None
        # Push-телеметрия робота (как ручная вкладка): кэш текущих координат/энкодера.
        self._robot_tlm_id: str | None = None
        # Хэндл fanout-подписки на телеметрию робота — для явной отписки.
        self._robot_tlm_handle: Any = None
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
        # Оставлена «про запас»: если push когда-нибудь дойдёт — метка обновится сама.
        self._bind_robot_telemetry(device_id)
        # Разовый pull-опрос — чтобы «Робот сейчас» не висела «—» сразу после выбора робота.
        self._pull_robot_once()
        cam = self._widget.camera_id
        vfd = self._widget.vfd_id
        self._bind_progress(cam)
        self._widget.set_status(
            f"Робот «{device_id}». Шаг 1: наведи плату (live 5/5) и жми «Зафиксировать». "
            f"Шаг 2: жми «Точка N» по номерам. Шаг 3: прогон ленты + «Считать E2»."
        )
        # Авто-старт сессии (кнопки «Начать сессию» больше нет).
        self._presenter.begin(cam, device_id, vfd)

    def _bind_robot_telemetry(self, device_id: str) -> None:
        """Подписаться на devices.state.<id>.status → кэш x/y/encoder робота (push)."""
        if self._bindings is None or not device_id or device_id == self._robot_tlm_id:
            return
        # Смена робота: сначала снять старую fanout-подписку (bind_fanout НЕ
        # дедуплицирует — без отписки callbacks копятся на каждую смену).
        self._unbind_robot_telemetry()
        self._robot_tlm_id = device_id
        path = f"devices.state.{device_id}.status"
        if hasattr(self._bindings, "bind_fanout"):
            self._robot_tlm_handle = self._bindings.bind_fanout(path, self._on_robot_status, owner=self._widget)

    def _on_robot_status(self, _path: str, value: Any) -> None:
        """Статус робота (push devices.state.<id>.status ИЛИ ответ pull — одна форма)."""
        xy, enc = self._extract_xy_enc(value)
        if xy is None:
            return
        self._robot_xy = xy
        self._robot_enc = enc
        self._widget.set_robot_live(xy[0], xy[1], enc)

    @staticmethod
    def _extract_xy_enc(data: Any) -> tuple[tuple[float, float] | None, int | None]:
        """Достать (x_mm, y_mm) + encoder из статуса/телеметрии (push и pull — одна форма)."""
        if not isinstance(data, dict):
            return None, None
        tel = data.get("telemetry") or {}
        x = tel.get("x_mm")
        y = tel.get("y_mm")
        if x is None or y is None:
            return None, None
        enc = data.get("encoder")
        return (float(x), float(y)), (int(enc) if enc is not None else None)

    def _pull_robot_once(self) -> None:
        """Разовый pull `robot_get_telemetry` → обновить «Робот сейчас» (по запросу)."""
        if self._robot_presenter is None or not self._robot_id:
            return
        self._robot_presenter.get_telemetry(self._robot_id, lambda data: self._on_robot_status("", data))

    def unbind(self) -> None:
        """Полная отписка контроллера: прогресс калибровки + телеметрия робота."""
        self._unbind_progress()
        self._unbind_robot_telemetry()

    def _unbind_robot_telemetry(self) -> None:
        """Снять fanout-подписку на телеметрию робота (если была) и сбросить метку."""
        if self._robot_tlm_handle is not None and hasattr(self._bindings, "unbind_fanout"):
            self._bindings.unbind_fanout(self._robot_tlm_handle)
        self._robot_tlm_handle = None
        self._robot_tlm_id = None

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
            self._progress_handle = self._bindings.bind_fanout(path, self._on_progress_push, owner=self._widget)
            self._progress_owner_path = path

    def _unbind_progress(self) -> None:
        """Снять fanout-подписку на прогресс (если была) и сбросить метки.

        bind_fanout НЕ дедуплицирует — без явной отписки повторный bind
        (смена камеры / повторный begin) накапливал бы callbacks.
        """
        if self._progress_handle is not None and hasattr(self._bindings, "unbind_fanout"):
            self._bindings.unbind_fanout(self._progress_handle)
        self._progress_handle = None
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
        """Шаг 2 «Точка N»: записать только координаты робота + энкодер E1.

        Пиксели в этой группе НЕ пишутся — они фиксируются на Шаге 1 («Зафиксировать»).
        Координаты робота берём СВЕЖИМИ по запросу — pull `robot_get_telemetry` в момент
        нажатия (push до GUI не доходит). Сломанный `cal_set_robot_point` не используется;
        пишем через `cal_set_point` (плагин просто сохраняет, без IPC к роботу).
        """
        if self._robot_presenter is not None and self._robot_id:
            self._widget.set_status(f"Точка {index + 1}: опрос робота…")
            self._robot_presenter.get_telemetry(
                self._robot_id,
                lambda data, idx=index: self._on_point_telemetry(idx, data),
            )
            return
        # Фолбэк (нет presenter, напр. юнит-тесты): берём последний кэш push.
        self._write_point(index, self._robot_xy, self._robot_enc)

    def _on_point_telemetry(self, index: int, data: Any) -> None:
        """Ответ pull-опроса под «Точка N»: обновить «Робот сейчас» + записать точку."""
        xy, enc = self._extract_xy_enc(data)
        if xy is not None:
            self._robot_xy = xy
            self._robot_enc = enc
            self._widget.set_robot_live(xy[0], xy[1], enc)
        self._write_point(index, xy, enc)

    def _write_point(self, index: int, xy: tuple[float, float] | None, enc: int | None) -> None:
        """Шаг 2: записать только координаты робота + энкодер E1 (px фиксируются на Шаге 1)."""
        if xy is None:
            self._widget.set_status("Нет телеметрии робота — проверь подключение (вкладка «Ручное управление»).")
            return
        x, y = xy
        self._presenter.set_point(index, mm=[x, y], enc=enc)
        captured = bool((self._last_snapshot or {}).get("captured"))
        hint = "" if captured else " (сначала нажми «Зафиксировать» на Шаге 1 для пикселей)"
        self._widget.set_status(f"Точка {index + 1}: робот ({x:.1f}, {y:.1f}), enc={enc}{hint}")

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
    # Презентер робота (target=devices) — pull-телеметрия по запросу (тот же путь, что «Обновить»).
    robot_presenter = RobotPresenter(
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    controller = CalibrationController(widget, presenter, bindings=bindings, robot_presenter=robot_presenter)
    return widget, controller, presenter
