# -*- coding: utf-8 -*-
"""Декларация секций для ServicesTab (BaseTreeNavTab).

Структура (Settings-стиль, ветвящееся дерево):

    ▾ Сервисы               (services_root — placeholder «выберите сервис»)
        <name>              (динамически из ServiceRegistry.list())
        ...
    Нейронные сети          (placeholder для Phase 14+)
    Пути                    (__service_paths__)

Каждый сервисный узел — ``_ServiceSection`` с информационной карточкой
(имя, lifecycle) и тремя кнопками управления в ``action_buttons()``
(Запустить / Остановить / Перезапуск). Кнопки — заглушка до Task 3.7.

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

from .presenter import ServicesPresenter

if TYPE_CHECKING:
    from multiprocess_framework.modules.service_module import ServiceLifecycle
    from multiprocess_prototype.frontend.app_context import AppContext


# ---------------------------------------------------------------------------
# _ServiceInfoCard — карточка сервиса с именем и lifecycle-статусом
# ---------------------------------------------------------------------------


class _ServiceInfoCard(QWidget):
    """Простая карточка с информацией о сервисе."""

    def __init__(self, name: str, lifecycle: "ServiceLifecycle", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        name_label = QLabel(f"<b>Сервис:</b> {name}")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        status_label = QLabel(f"<b>Статус:</b> {lifecycle.value}")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        layout.addStretch()


# ---------------------------------------------------------------------------
# _ServiceSection — реальная сервисная секция с карточкой и кнопками
# ---------------------------------------------------------------------------


class _ServiceSection:
    """Секция одного сервиса: _ServiceInfoCard в content + 3 кнопки в action-колонке."""

    def __init__(
        self,
        ctx: "AppContext",
        name: str,
        title: str,
        lifecycle: "ServiceLifecycle",
    ) -> None:
        self._ctx = ctx
        self._key = name
        self._title = title
        self._lifecycle = lifecycle
        self._widget: QWidget | None = None
        self._buttons: list[QPushButton] = []

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

    # -------- Internal --------

    def _build_widget(self) -> None:
        self._widget = _ServiceInfoCard(self._key, self._lifecycle)

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
        # TODO (Task 3.7): реальная интеграция с backend (start/stop/restart через presenter).
        QMessageBox.information(
            self._widget,
            f"Сервис: {self._title}",
            f"Действие «{label}» для сервиса «{self._title}» будет добавлено в Task 3.7.",
        )


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
# _ServicePathsSection — секция управления директориями сервисов
# ---------------------------------------------------------------------------


class _ServicePathsSection:
    """Секция «Пути» — ServicePathsSubtabWidget."""

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx
        self._widget: QWidget | None = None

    @property
    def key(self) -> str:
        return "__service_paths__"

    @property
    def title(self) -> str:
        return "Пути"

    def widget(self) -> QWidget:
        if self._widget is None:
            from .paths_subtab import ServicePathsSubtabWidget

            presenter = ServicesPresenter(self._ctx)
            self._widget = ServicePathsSubtabWidget(presenter)
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...


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


def _service_paths_factory(ctx: "AppContext") -> _ServicePathsSection:
    return _ServicePathsSection(ctx)


def _make_service_factory(
    name: str,
    title: str,
    lifecycle: "ServiceLifecycle",
) -> "Callable[[AppContext], _ServiceSection]":
    def factory(ctx: "AppContext") -> _ServiceSection:
        return _ServiceSection(ctx, name, title, lifecycle)

    return factory


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def build_services_sections(ctx: "AppContext") -> "list[SectionSpec[AppContext]]":
    """Сформировать декларацию секций ServicesTab.

    Структура:
        - «Сервисы» (services_root, родитель) — только если есть хотя бы один
          сервис в ServiceRegistry. Иначе родительский узел не создаётся.
        - Под ним — N сервисных секций (lazy) из ServiceRegistry.list().
        - Top-level «Нейронные сети» — всегда присутствует как placeholder.
        - Top-level «Пути» (__service_paths__) — управление директориями.
    """
    presenter = ServicesPresenter(ctx)
    service_data = presenter.list_services()  # [(name, title, lifecycle), ...]

    sections: list[SectionSpec[AppContext]] = []

    if service_data:
        sections.append(
            SectionSpec(
                key="services_root",
                title="Сервисы",
                factory=_services_root_factory,
            )
        )
        for name, title, lifecycle in service_data:
            sections.append(
                SectionSpec(
                    key=name,
                    title=title,
                    factory=_make_service_factory(name, title, lifecycle),
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
    sections.append(
        SectionSpec(
            key="__service_paths__",
            title="Пути",
            factory=_service_paths_factory,
        )
    )
    return sections
