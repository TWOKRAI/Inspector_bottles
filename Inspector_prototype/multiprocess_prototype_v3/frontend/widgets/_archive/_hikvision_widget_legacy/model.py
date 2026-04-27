# multiprocess_prototype_v3/frontend/widgets/hikvision_widget/model.py
"""HikvisionModel — данные и операции: регистры, колбэки."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.registers.schemas.camera_tab import CAMERA_REGISTER

from .schemas import HikvisionUiConfig

if TYPE_CHECKING:
    from .callbacks import HikvisionWidgetCallbacks


class HikvisionModel:
    """
    Слой данных Hikvision: чтение/запись регистра, делегирование команд колбэкам.

    Не знает о View и Presenter.
    """

    def __init__(
        self,
        *,
        rm: Optional[IRegistersManagerGui],
        callbacks: "HikvisionWidgetCallbacks",
        ui: HikvisionUiConfig,
    ) -> None:
        self._rm = rm
        self._callbacks = callbacks
        self._ui = ui

    def enum_devices(self) -> None:
        """Запустить перечисление устройств (через колбэк)."""
        if self._callbacks.on_enum_devices:
            self._callbacks.on_enum_devices()

    def open_camera(self, camera_index: int) -> None:
        """Открыть камеру по индексу."""
        if self._callbacks.on_open:
            self._callbacks.on_open(camera_index=camera_index)

    def close_camera(self) -> None:
        """Закрыть камеру."""
        if self._callbacks.on_close:
            self._callbacks.on_close()

    def start_grabbing(self) -> None:
        """Запустить захват."""
        if self._callbacks.on_start_grabbing:
            self._callbacks.on_start_grabbing()

    def stop_grabbing(self) -> None:
        """Остановить захват."""
        if self._callbacks.on_stop_grabbing:
            self._callbacks.on_stop_grabbing()

    def get_parameters(self) -> None:
        """Запросить параметры камеры (колбэк)."""
        if self._callbacks.on_get_parameters:
            self._callbacks.on_get_parameters()

    def set_parameters(self, frame_rate: float, exposure: float, gain: float) -> None:
        """Отправить параметры камере (колбэк)."""
        if self._callbacks.on_set_parameters:
            self._callbacks.on_set_parameters(frame_rate, exposure, gain)

    def get_params_for_set(
        self,
        fallback_from_lines: Callable[[], Tuple[float, float, float]],
    ) -> Tuple[float, float, float]:
        """
        Тройка для Set Parameters: из регистра, если есть rm; иначе из View (line edit).

        View передаёт fallback — модель не знает о виджетах, только о наличии регистра.
        """
        if self._rm is not None:
            return self.read_params_from_register()
        return fallback_from_lines()

    def read_params_from_register(self) -> Tuple[float, float, float]:
        """Кортеж (frame_rate, exposure, gain) из регистра. Fallback — defaults из ui."""
        if self._rm is None:
            return tuple(s.read_fallback_default for s in self._ui.hikvision_spinbox_rows)
        reg = self._rm.get_register(CAMERA_REGISTER)
        if not reg:
            return tuple(s.read_fallback_default for s in self._ui.hikvision_spinbox_rows)
        out: list[float] = []
        for spec in self._ui.hikvision_spinbox_rows:
            v = getattr(reg, spec.register_field, spec.read_fallback_default)
            out.append(float(v))
        return tuple(out)

    def apply_params_to_register(self, params: Dict[str, Any]) -> None:
        """Записать в регистр значения из словаря ответа камеры."""
        if not params or self._rm is None:
            return
        for api_key, field in self._ui.hikvision_api_field_pairs():
            if api_key in params:
                self._rm.set_field_value(CAMERA_REGISTER, field, float(params[api_key]))
