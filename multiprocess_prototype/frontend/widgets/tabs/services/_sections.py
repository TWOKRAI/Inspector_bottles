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
(Запустить / Остановить / Перезапуск). Task 3.7: кнопки подключены к
реальным вызовам presenter.start_service/stop_service/restart_service.

Узлы-плейсхолдеры (root + neural_networks) реализованы через
``_PlaceholderSection`` — текстовая метка по центру.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_framework.modules.service_module import ServiceLifecycle
from multiprocess_prototype.domain.app_services import AppServices

from .presenter import ServicesPresenter


# ---------------------------------------------------------------------------
# _ServiceInfoCard — карточка сервиса с именем и реактивным lifecycle-статусом
# ---------------------------------------------------------------------------


class _ServiceInfoCard(QWidget):
    """Карточка с именем сервиса и обновляемым статус-лейблом."""

    def __init__(self, name: str, lifecycle: ServiceLifecycle, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        name_label = QLabel(f"<b>Сервис:</b> {name}")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # Статус-лейбл обновляется при изменении lifecycle
        self._status_label = QLabel(f"<b>Статус:</b> {lifecycle.value}")
        self._status_label.setObjectName(f"service_status_{name}")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()

    def update_status(self, lifecycle: ServiceLifecycle) -> None:
        """Обновить отображаемый статус сервиса.

        Args:
            lifecycle: Новое состояние жизненного цикла.
        """
        self._status_label.setText(f"<b>Статус:</b> {lifecycle.value}")


# ---------------------------------------------------------------------------
# _ServiceSection — реальная сервисная секция с карточкой и кнопками
# ---------------------------------------------------------------------------


class _ServiceSection:
    """Секция одного сервиса: _ServiceInfoCard в content + 3 кнопки в action-колонке.

    Task 3.7: кнопки «Запустить / Остановить / Перезапуск» подключены к
    реальным вызовам presenter. Статус-лейбл обновляется после каждого клика
    напрямую через _refresh_view() — без Qt-сигналов между секциями.

    Lifecycle читается из ServiceRegistry (не из StateProxy) — StateProxy
    недоступен в GUI-процессе. Это MVP; IPC-sync — Phase 4+.
    """

    def __init__(
        self,
        services: AppServices,
        name: str,
        title: str,
        lifecycle: ServiceLifecycle,
        presenter: ServicesPresenter,
    ) -> None:
        self._services = services
        self._key = name
        self._title = title
        self._initial_lifecycle = lifecycle
        self._presenter = presenter
        self._card: _ServiceInfoCard | None = None
        self._widget: QWidget | None = None
        self._btn_start: QPushButton | None = None
        self._btn_stop: QPushButton | None = None
        self._btn_restart: QPushButton | None = None

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
        if self._btn_start is None:
            self._build_buttons()
        buttons: list[QWidget] = []
        for btn in (self._btn_start, self._btn_stop, self._btn_restart):
            if btn is not None:
                buttons.append(btn)
        return buttons

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    # -------- Internal --------

    def _build_widget(self) -> None:
        """Построить виджет-карточку с реактивным статус-лейблом."""
        self._card = _ServiceInfoCard(self._key, self._initial_lifecycle)
        self._widget = self._card

    def _build_buttons(self) -> None:
        """Построить три кнопки действий и подключить обработчики."""
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        self._btn_start = QPushButton("Запустить")
        self._btn_start.setToolTip(f"Запустить сервис {self._title}")
        self._btn_start.clicked.connect(self._on_start_click)

        self._btn_stop = QPushButton("Остановить")
        self._btn_stop.setToolTip(f"Остановить сервис {self._title}")
        self._btn_stop.clicked.connect(self._on_stop_click)

        self._btn_restart = QPushButton("Перезапуск")
        self._btn_restart.setToolTip(f"Перезапустить сервис {self._title}")
        self._btn_restart.clicked.connect(self._on_restart_click)

        # Установить начальное состояние disabled/enabled по lifecycle
        self._refresh_button_state()

        # Привязать к permission system через AuthFacade Protocol (F.6).
        for btn in (self._btn_start, self._btn_stop, self._btn_restart):
            install_permission_aware_enable(btn, "tabs.services.edit", self._services.auth)

    def _on_start_click(self) -> None:
        """Запустить сервис и обновить отображение."""
        self._presenter.start_service(self._key)
        self._refresh_view()

    def _on_stop_click(self) -> None:
        """Остановить сервис и обновить отображение."""
        self._presenter.stop_service(self._key)
        self._refresh_view()

    def _on_restart_click(self) -> None:
        """Перезапустить сервис и обновить отображение."""
        self._presenter.restart_service(self._key)
        self._refresh_view()

    def _refresh_view(self) -> None:
        """Прочитать актуальный lifecycle из registry и обновить UI."""
        lifecycle = self._presenter.get_lifecycle(self._key)
        if lifecycle is None:
            return
        if self._card is not None:
            self._card.update_status(lifecycle)
        self._refresh_button_state(lifecycle)

    def _refresh_button_state(self, lifecycle: ServiceLifecycle | None = None) -> None:
        """Установить disabled/enabled для кнопок по текущему lifecycle.

        Args:
            lifecycle: Явный lifecycle (передаётся из _refresh_view чтобы
                       не читать из registry повторно). Если None — читает сам.
        """
        if lifecycle is None:
            lifecycle = self._presenter.get_lifecycle(self._key) or self._initial_lifecycle

        is_running = lifecycle == ServiceLifecycle.RUNNING
        is_error = lifecycle == ServiceLifecycle.ERROR

        if self._btn_start is not None:
            self._btn_start.setEnabled(not is_running)
        if self._btn_stop is not None:
            self._btn_stop.setEnabled(is_running)
        if self._btn_restart is not None:
            self._btn_restart.setEnabled(is_running or is_error)


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

    def __init__(self, services: AppServices) -> None:
        self._services = services
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

            presenter = ServicesPresenter(self._services)
            self._widget = ServicePathsSubtabWidget(presenter)
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...


# ---------------------------------------------------------------------------
# Фабрики для SectionSpec
# ---------------------------------------------------------------------------


# BaseTreeNavTab вызывает factory(ctx_arg) с self._ctx (= None после миграции).
# Фабрики игнорируют ctx_arg и замыкают services (паттерн Settings _make_factory).


def _services_root_factory(_ctx_arg: object) -> _PlaceholderSection:
    return _PlaceholderSection(
        key="services_root",
        title="Сервисы",
        text="Выберите сервис из списка слева.",
    )


def _nn_placeholder_factory(_ctx_arg: object) -> _PlaceholderSection:
    return _PlaceholderSection(
        key="neural_networks",
        title="Нейронные сети",
        text="Нейронные сети будут доступны в Phase 14+",
    )


def _make_paths_factory(services: AppServices) -> "Callable[[object], _ServicePathsSection]":
    return lambda _ctx_arg: _ServicePathsSection(services)


def _make_service_factory(
    services: AppServices,
    name: str,
    title: str,
    lifecycle: ServiceLifecycle,
) -> "Callable[[object], _ServiceSection]":
    def factory(_ctx_arg: object) -> _ServiceSection:
        # Presenter создаётся один раз на секцию и делегирует lifecycle в
        # services.services (адаптер владеет кэшем экземпляров).
        presenter = ServicesPresenter(services)
        return _ServiceSection(services, name, title, lifecycle, presenter)

    return factory


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def build_services_sections(services: AppServices) -> "list[SectionSpec]":
    """Сформировать декларацию секций ServicesTab.

    Task E.4: принимает AppServices вместо AppContext.

    Структура:
        - «Сервисы» (services_root, родитель) — только если есть хотя бы один
          сервис в ServiceManager. Иначе родительский узел не создаётся.
        - Под ним — N сервисных секций (lazy) из services.services.list_services().
        - Top-level «Нейронные сети» — всегда присутствует как placeholder.
        - Top-level «Пути» (__service_paths__) — управление директориями.
    """
    presenter = ServicesPresenter(services)
    service_data = presenter.list_services()  # [(name, title, lifecycle), ...]

    sections: list[SectionSpec] = []

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
                    factory=_make_service_factory(services, name, title, lifecycle),
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
            factory=_make_paths_factory(services),
        )
    )
    return sections
