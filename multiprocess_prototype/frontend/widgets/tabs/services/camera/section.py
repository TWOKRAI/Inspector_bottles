"""_CameraSection — секция «Камера» во вкладке Services (подробный фасад).

Строит CameraSettingsWidget + CameraSettingsPresenter, связывает сигналы и
привязывает actual-метки к state store через bindings. Без cv2 — live через IPC.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .presenter import CameraSettingsPresenter
from .widget import CameraSettingsWidget


class _CameraSection:
    """Секция «Камера»: подробный фасад настроек вебкамеры (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: CameraSettingsWidget | None = None
        self._presenter: CameraSettingsPresenter | None = None
        self._actual_handles: list[Any] = []

    @property
    def key(self) -> str:
        return "__camera__"

    @property
    def title(self) -> str:
        return "Камера"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        # Каждый показ — пересобрать live-состояние и привязки (топология могла измениться).
        if self._widget is not None:
            self._refresh_live()

    def on_deactivated(self) -> None:
        self._unbind_actual()

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self._widget = CameraSettingsWidget()
        self._presenter = CameraSettingsPresenter(
            bridge=getattr(self._runtime, "topology_bridge", None),
            topology=getattr(self._services, "topology", None),
            recipes=getattr(self._services, "recipes", None),
        )
        w, p = self._widget, self._presenter
        w.param_changed.connect(p.apply_param)
        w.mjpg_changed.connect(p.apply_mjpg)
        w.resolution_changed.connect(p.apply_resolution)
        w.fps_changed.connect(p.apply_fps)
        w.save_clicked.connect(self._on_save)
        self._refresh_live()

    def _on_save(self) -> None:
        if self._presenter is None or self._widget is None:
            return
        ok = self._presenter.save()
        self._widget.set_status(
            "Сохранено в активный рецепт." if ok else "Не удалось сохранить (нет активного рецепта или изменений)."
        )

    def _refresh_live(self) -> None:
        """Обновить статус live и (пере)привязать actual-метки к state store."""
        if self._presenter is None or self._widget is None:
            return
        proc = self._presenter.camera_process_name()
        if proc is None:
            self._widget.set_status(
                "Камера не запущена. Запустите рецепт «камера → дисплей» для live-настройки "
                "и actual-параметров; правки можно сохранить в рецепт."
            )
        else:
            self._widget.set_status("")
        self._bind_actual(proc)

    def _unbind_actual(self) -> None:
        bindings = getattr(self._runtime, "bindings", None)
        if bindings is not None:
            for h in self._actual_handles:
                try:
                    bindings.unbind(h)
                except Exception:
                    pass
        self._actual_handles = []

    def _bind_actual(self, process_name: str | None) -> None:
        """Привязать actual-метки виджета к processes.{proc}.state.cam.actual.*."""
        self._unbind_actual()
        bindings = getattr(self._runtime, "bindings", None)
        if bindings is None or not process_name or self._widget is None:
            return
        labels = self._widget.actual_labels
        base = f"processes.{process_name}.state.cam.actual"

        def _num(unit: str = ""):
            return lambda v: f"{float(v):.0f}{unit}" if isinstance(v, (int, float)) else str(v)

        self._actual_handles.append(bindings.bind(f"{base}.fps", labels["fps"], "text", formatter=_num(" fps")))
        self._actual_handles.append(bindings.bind(f"{base}.exposure", labels["exposure"], "text", formatter=_num()))
        self._actual_handles.append(bindings.bind(f"{base}.gain", labels["gain"], "text", formatter=_num()))
        self._actual_handles.append(bindings.bind(f"{base}.fourcc", labels["fourcc"], "text"))
        # Разрешение собираем из width+height.
        res = {"width": 0, "height": 0}

        def _res(key):
            def _fmt(v):
                try:
                    res[key] = int(float(v))
                except (TypeError, ValueError):
                    pass
                return f"{res['width']}×{res['height']}"

            return _fmt

        self._actual_handles.append(
            bindings.bind(f"{base}.width", labels["resolution"], "text", formatter=_res("width"))
        )
        self._actual_handles.append(
            bindings.bind(f"{base}.height", labels["resolution"], "text", formatter=_res("height"))
        )


def build_camera_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Камера",
) -> SectionSpec:
    """SectionSpec для секции «Камера» (lazy). parent_key — для группировки."""
    section = _CameraSection(services, runtime)
    return SectionSpec(
        key="__camera__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
