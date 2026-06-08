# -*- coding: utf-8 -*-
"""_HikvisionSection — секция «Hikvision камера» во вкладке Services.

Строит HikvisionSettingsWidget + HikvisionSettingsPresenter, связывает сигналы.
Результаты enum/get_parameters приходят в main-thread (RequestRunner) и
обновляют поля виджета. Изображение — в дисплее активного рецепта.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .presenter import HikvisionSettingsPresenter
from .widget import HikvisionSettingsWidget


class _HikvisionSection:
    """Секция «Hikvision камера» (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: HikvisionSettingsWidget | None = None
        self._presenter: HikvisionSettingsPresenter | None = None
        self._runner: Any = None

    @property
    def key(self) -> str:
        return "__hikvision__"

    @property
    def title(self) -> str:
        return "Hikvision камера"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        self._refresh_status()

    def on_deactivated(self) -> None: ...

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

        self._widget = HikvisionSettingsWidget()
        # RequestRunner парентим к виджету — живёт вместе с секцией, шлёт сигнал в main-thread.
        self._runner = RequestRunner(parent=self._widget)
        self._presenter = HikvisionSettingsPresenter(
            bridge=getattr(self._runtime, "topology_bridge", None),
            topology=getattr(self._services, "topology", None),
            command_sender=getattr(self._runtime, "command_sender", None),
            request_runner=self._runner,
        )

        w = self._widget
        w.enum_requested.connect(self._on_enum)
        w.open_requested.connect(self._on_open)
        w.close_requested.connect(self._on_close)
        w.start_requested.connect(self._on_start)
        w.stop_requested.connect(self._on_stop)
        w.get_params_requested.connect(self._on_get_params)
        w.apply_params_requested.connect(self._on_apply_params)
        w.open_sdk_app_requested.connect(self._on_open_sdk_app)

        self._refresh_status()

    # --- обработчики сигналов виджета ---

    def _on_enum(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        self._widget.set_status("Поиск устройств…")
        self._presenter.enum_devices(self._on_devices)

    def _on_devices(self, devices: list[dict]) -> None:
        if self._widget is None:
            return
        self._widget.set_devices(devices)
        if devices:
            self._widget.set_status(f"Найдено устройств: {len(devices)}")
        else:
            self._widget.set_status(
                "Устройства не найдены. Нужен запущенный рецепт с камерой Hikvision "
                "(процесс камеры) — либо используйте окно SDK App."
            )

    def _on_open(self, index: int) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.open(index)
        self._widget.set_status("Камера открыта." if ok else self._no_live_hint())

    def _on_close(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.close()
        self._widget.set_status("Камера закрыта." if ok else self._no_live_hint())

    def _on_start(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.start()
        self._widget.set_status("Захват запущен." if ok else self._no_live_hint())

    def _on_stop(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.stop()
        self._widget.set_status("Захват остановлен." if ok else self._no_live_hint())

    def _on_get_params(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        self._widget.set_status("Запрос параметров…")
        self._presenter.get_parameters(self._on_params)

    def _on_params(self, params: dict) -> None:
        if self._widget is None:
            return
        if not params:
            self._widget.set_status(self._no_live_hint())
            return
        self._widget.set_params(
            float(params.get("frame_rate", 0.0)),
            float(params.get("exposure_time", 0.0)),
            float(params.get("gain", 0.0)),
        )
        self._widget.set_status("Параметры получены.")

    def _on_apply_params(self, fps: float, exposure: float, gain: float) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.set_parameters(fps, exposure, gain)
        self._widget.set_status("Параметры применены." if ok else self._no_live_hint())

    def _on_open_sdk_app(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.open_sdk_app()
        self._widget.set_status("Окно SDK App запущено." if ok else "Не удалось запустить SDK App.")

    # --- статус ---

    def _refresh_status(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        if self._presenter.is_live:
            self._widget.set_status("Камера активна (live-управление доступно).")
        else:
            self._widget.set_status(
                "Камера не запущена. Активируйте рецепт с камерой Hikvision для "
                "live-управления, либо откройте окно SDK App."
            )

    def _no_live_hint(self) -> str:
        return (
            "Команда не отправлена: нет запущенного процесса камеры Hikvision. "
            "Активируйте рецепт hikvision_inspect или используйте окно SDK App."
        )


def build_hikvision_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Hikvision Camera",
) -> SectionSpec:
    """SectionSpec для секции «Hikvision Camera» (lazy). parent_key — для группировки."""
    section = _HikvisionSection(services, runtime)
    return SectionSpec(
        key="__hikvision__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
