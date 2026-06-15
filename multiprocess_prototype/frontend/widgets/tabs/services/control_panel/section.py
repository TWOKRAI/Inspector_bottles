"""_ControlPanelSection — секция «Пульт» во вкладке Services.

Строит ControlPanelWidget + presenter. Контролы рендерятся реактивно из state
(glob ``processes.*.state.control_panel.controls``). Операция над контролом —
live-команда плагину; правка набора (add/remove) — live + персист в рецепт
(SetPluginConfig через services.commands, как редактор Pipeline).

Нода control_panel резолвится из топологии (process_name + индекс плагина) —
для персиста в нужную ноду. Если ноды в активном рецепте нет, добавление контролов
не персистится (нужна нода «Пульт» в рецепте).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .presenter import ControlPanelPresenter
from .widget import ControlPanelWidget

_PLUGIN_NAME = "control_panel"


class _ControlPanelSection:
    """Секция «Пульт»: карточка контролов (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: ControlPanelWidget | None = None
        self._presenter: ControlPanelPresenter | None = None
        self._handles: list[Any] = []

    @property
    def key(self) -> str:
        return "__control_panel__"

    @property
    def title(self) -> str:
        return "Пульт"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        """Кнопки action-колонки секции. У пульта их нет (контролы — в карточке)."""
        return []

    def on_activated(self) -> None:
        self._bind()

    def on_deactivated(self) -> None:
        self._unbind()

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self._widget = ControlPanelWidget()
        self._presenter = ControlPanelPresenter(
            bridge=getattr(self._runtime, "topology_bridge", None),
            services=self._services,
        )
        self._widget.control_operated.connect(self._on_operated)
        self._widget.control_add_requested.connect(self._on_add)
        self._widget.control_remove_requested.connect(self._on_remove)
        self._bind()

    def _on_operated(self, control_id: str, value: object) -> None:
        if self._presenter is not None:
            self._presenter.operate(control_id, value)

    def _on_add(self, spec: dict) -> None:
        if self._presenter is None or self._widget is None:
            return
        proc, idx = self._resolve_node()
        new_controls = self._widget.current_controls() + [spec]
        self._presenter.add(spec, proc or "", idx, new_controls)

    def _on_remove(self, control_id: str) -> None:
        if self._presenter is None or self._widget is None:
            return
        proc, idx = self._resolve_node()
        new_controls = [c for c in self._widget.current_controls() if c.get("id") != control_id]
        self._presenter.remove(control_id, proc or "", idx, new_controls)

    def _resolve_node(self) -> tuple[str | None, int]:
        """Найти ноду control_panel в активной топологии → (process_name, plugin_index)."""
        bridge = getattr(self._runtime, "topology_bridge", None)
        topo = getattr(bridge, "topology", None) if bridge is not None else None
        if not isinstance(topo, dict):
            return None, 0
        for proc in topo.get("processes", []) or []:
            for idx, pl in enumerate(proc.get("plugins", []) or []):
                if isinstance(pl, dict) and pl.get("plugin_name") == _PLUGIN_NAME:
                    return proc.get("process_name"), idx
        return None, 0

    def _unbind(self) -> None:
        bindings = getattr(self._runtime, "bindings", None)
        if bindings is not None:
            for handle in self._handles:
                try:
                    bindings.unbind(handle)
                except Exception:
                    pass
        self._handles = []

    def _bind(self) -> None:
        """Привязать набор контролов к state store (реактивный рендер)."""
        self._unbind()
        bindings = getattr(self._runtime, "bindings", None)
        if bindings is None or self._widget is None:
            return
        # Нода control_panel — источник в рецепте; имя процесса задаёт пользователь,
        # поэтому glob по всем процессам.
        self._handles.append(bindings.bind("processes.*.state.control_panel.controls", self._widget, "set_controls"))


def build_control_panel_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Пульт",
) -> SectionSpec:
    """SectionSpec для секции «Пульт» (lazy). parent_key — для группировки."""
    section = _ControlPanelSection(services, runtime)
    return SectionSpec(
        key="__control_panel__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
