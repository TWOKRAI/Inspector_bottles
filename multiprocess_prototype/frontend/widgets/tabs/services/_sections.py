# -*- coding: utf-8 -*-
"""Декларация секций для ServicesTab (BaseTreeNavTab).

Структура (Settings-стиль, ветвящееся дерево):

    ▾ Сервисы               (services_root — placeholder «выберите сервис»)
        Камеры              (camera_service)
        База данных         (database)
        Управление роботом  (robot_control)
        Сохранение кадров   (frame_saver)
    Нейронные сети          (placeholder для Phase 14+)

Каждый сервисный узел — ``_ServiceSection`` с ``RegisterView`` в качестве
``widget()`` и тремя кнопками управления в ``action_buttons()`` (Запустить /
Остановить / Перезапуск). Кнопки отдают визуальный QMessageBox-фидбек до
реализации реальной интеграции с бэкендом.

Узлы-плейсхолдеры (root + neural_networks) реализованы через
``_PlaceholderSection`` — текстовая метка по центру.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.frontend.forms import RegisterView

from .presenter import ServicesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


# ---------------------------------------------------------------------------
# _ServiceSection — реальная сервисная секция с RegisterView и кнопками
# ---------------------------------------------------------------------------


class _ServiceSection:
    """Секция одного сервиса: RegisterView в content + 3 кнопки в action-колонке."""

    def __init__(
        self,
        ctx: "AppContext",
        plugin_name: str,
        title: str,
        fields: list,
    ) -> None:
        self._ctx = ctx
        self._key = plugin_name
        self._title = title
        self._fields = fields
        self._widget: QWidget | None = None
        self._buttons: list[QPushButton] = []
        self._register_view: RegisterView | None = None

    # -------- SectionProtocol --------

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build_widget()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        if not self._buttons:
            self._build_buttons()
        return list(self._buttons)

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    # -------- SectionWithEvents (bus подписка через BaseTreeNavTab) --------

    def bus_change_callback(self) -> Callable[[], None] | None:
        """Callback для подписки на ActionBus — обновлять editor при undo/redo."""
        return self._on_bus_changed

    # -------- Internal --------

    def _build_widget(self) -> None:
        form_ctx = self._ctx.form_context()
        view = RegisterView(self._fields, form_ctx=form_ctx)
        view.field_changed.connect(self._on_field_changed)
        self._register_view = view
        self._widget = view

    def _build_buttons(self) -> None:
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        for label in ("Запустить", "Остановить", "Перезапуск"):
            btn = QPushButton(label)
            btn.setToolTip(f"{label} сервис {self._title}")
            btn.clicked.connect(lambda _checked=False, lbl=label: self._on_button_click(lbl))
            self._buttons.append(btn)

        _auth = getattr(self._ctx, "auth", None)
        auth_state = getattr(_auth, "state", None) if _auth is not None else None
        for btn in self._buttons:
            install_permission_aware_enable(btn, "tabs.services.edit", auth_state)

    def _on_button_click(self, label: str) -> None:
        # TODO: реальная интеграция с backend (start/stop/restart через presenter).
        # Пока — visible-stub, чтобы клик не был немым.
        QMessageBox.information(
            self._widget,
            f"Сервис: {self._title}",
            f"Действие «{label}» для сервиса «{self._title}» будет добавлено позже.",
        )

    def _on_field_changed(
        self,
        register_name: str,
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """Изменение параметра сервиса → ActionBus.execute(field_set)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

        action = V2ActionBuilder.field_set_timed(
            register_name,
            field_name,
            new_value,
            old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.execute(action)

    def _on_bus_changed(self) -> None:
        """Callback от ActionBus — обновить RegisterView при undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None or self._register_view is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        value = action.backward_patch.get("value") if event_type == "undo" else action.forward_patch.get("value")
        key = f"{register_name}.{action.field_name}"
        if key in self._register_view.editors():
            self._register_view.set_editor_value(key, value)


# ---------------------------------------------------------------------------
# _PlaceholderSection — заглушка с текстом по центру
# ---------------------------------------------------------------------------


class _PlaceholderSection:
    """Заглушка: текстовая метка по центру (без кнопок)."""

    def __init__(self, key: str, title: str, text: str) -> None:
        self._key = key
        self._title = title
        self._text = text
        self._widget: QWidget | None = None

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = self._build()
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    def _build(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(self._text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("role", "placeholder-italic")
        layout.addWidget(label)
        return w


# ---------------------------------------------------------------------------
# Фабрики для SectionSpec
# ---------------------------------------------------------------------------


def _services_root_factory(_ctx: "AppContext") -> _PlaceholderSection:
    return _PlaceholderSection(
        key="services_root",
        title="Сервисы",
        text="Выберите сервис из списка слева.",
    )


def _nn_placeholder_factory(_ctx: "AppContext") -> _PlaceholderSection:
    return _PlaceholderSection(
        key="neural_networks",
        title="Нейронные сети",
        text="Нейронные сети будут доступны в Phase 14+",
    )


def _make_service_factory(
    plugin_name: str,
    title: str,
    fields: list,
) -> Callable[["AppContext"], _ServiceSection]:
    def factory(ctx: "AppContext") -> _ServiceSection:
        return _ServiceSection(ctx, plugin_name, title, fields)

    return factory


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def build_services_sections(ctx: "AppContext") -> "list[SectionSpec[AppContext]]":
    """Сформировать декларацию секций ServicesTab.

    Структура:
        - «Сервисы» (services_root, родитель) — только если есть хотя бы один
          сервис в реестре с полями. Иначе родительский узел не создаётся.
        - Под ним — N сервисных секций (lazy).
        - Top-level «Нейронные сети» — всегда присутствует как placeholder.
    """
    presenter = ServicesPresenter(ctx)
    service_data = presenter.get_service_sections()  # [(title, plugin_name, fields), ...]

    sections: list[SectionSpec[AppContext]] = []
    if service_data:
        sections.append(
            SectionSpec(
                key="services_root",
                title="Сервисы",
                factory=_services_root_factory,
            )
        )
        for title, plugin_name, fields in service_data:
            sections.append(
                SectionSpec(
                    key=plugin_name,
                    title=title,
                    factory=_make_service_factory(plugin_name, title, fields),
                    parent_key="services_root",
                    lazy=True,
                )
            )
    sections.append(
        SectionSpec(
            key="neural_networks",
            title="Нейронные сети",
            factory=_nn_placeholder_factory,
        )
    )
    return sections
