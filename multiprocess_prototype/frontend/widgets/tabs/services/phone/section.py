"""_PhoneSection — секция «Телефон» во вкладке Services.

Строит PhoneServiceWidget + кнопки Вкл/Выкл (toggle сервера через bridge).
URL и QR вычисляются локально (GUI на той же машине, фикс. порт) — не гоняются
через state. Реактивно из state читаются только running и последнее слово.

Нода phone_camera — источник в рецепте; панель находит её по glob
processes.*.state.phone.*, toggle/сигналы маршрутизируются по plugin_name.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from Services.phone_gateway import qr as qr_mod
from Services.phone_gateway.netinfo import local_endpoints

from .presenter import PhoneServicePresenter
from .widget import PhoneServiceWidget

# Телефон — нода в рецепте (имя процесса задаёт пользователь), поэтому
# привязки идут по glob `processes.*.state.phone.*` — панель находит ноду в
# любом рецепте. Toggle-команда маршрутизируется по plugin_name (phone_camera).
_DEFAULT_PORT = 8080


class _PhoneSection:
    """Секция «Телефон»: карточка + кнопки Вкл/Выкл (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any, port: int = _DEFAULT_PORT) -> None:
        self._services = services
        self._runtime = runtime
        self._port = port
        self._widget: PhoneServiceWidget | None = None
        self._presenter: PhoneServicePresenter | None = None
        self._handles: list[Any] = []
        self._btn_on: QPushButton | None = None
        self._btn_off: QPushButton | None = None
        # Авто-обновление адреса при смене WiFi: таймер перечитывает IP, пока
        # панель открыта; QR пересоздаётся только когда адрес реально сменился.
        self._addr_timer: QTimer | None = None
        self._last_endpoints: list[tuple[str, str]] = []

    @property
    def key(self) -> str:
        return "__phone__"

    @property
    def title(self) -> str:
        return "Телефон"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        if self._btn_on is None:
            self._build_buttons()
        buttons: list[QWidget] = []
        for btn in (self._btn_on, self._btn_off):
            if btn is not None:
                buttons.append(btn)
        return buttons

    def on_activated(self) -> None:
        self._refresh()
        self._start_addr_timer()

    def on_deactivated(self) -> None:
        self._stop_addr_timer()
        self._unbind()

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self._widget = PhoneServiceWidget()
        self._presenter = PhoneServicePresenter(bridge=getattr(self._runtime, "topology_bridge", None))
        self._refresh()

    def _build_buttons(self) -> None:
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        self._btn_on = QPushButton("Включить")
        self._btn_on.setToolTip("Поднять сервер приёма фото/слова с телефона")
        self._btn_on.clicked.connect(self._on_start)

        self._btn_off = QPushButton("Выключить")
        self._btn_off.setToolTip("Погасить сервер приёма")
        self._btn_off.clicked.connect(self._on_stop)

        auth = getattr(self._services, "auth", None)
        for btn in (self._btn_on, self._btn_off):
            install_permission_aware_enable(btn, "tabs.services.edit", auth)

    def _on_start(self) -> None:
        if self._presenter is not None:
            self._presenter.start_server()

    def _on_stop(self) -> None:
        if self._presenter is not None:
            self._presenter.stop_server()

    def _refresh(self) -> None:
        """Показать адрес+QR (вычисляются локально) и (пере)привязать метки."""
        if self._widget is None:
            return
        self._last_endpoints = self._current_endpoints()
        self._apply_connection(self._last_endpoints)
        self._bind()

    def _current_endpoints(self) -> list[tuple[str, str]]:
        """[(метка_интерфейса, url)] для телефона, WiFi первым; порт фиксирован."""
        return [(label, f"http://{ip}:{self._port}/") for label, ip in local_endpoints()]

    def _apply_connection(self, endpoints: list[tuple[str, str]]) -> None:
        """Показать адрес(а) с метками и сгенерировать QR на основной адрес."""
        if self._widget is None:
            return
        qr_png = qr_mod.make_qr_png(endpoints[0][1]) if endpoints else None
        self._widget.set_connection(endpoints, qr_png)

    def _maybe_refresh_address(self) -> None:
        """Перечитать IP (смена WiFi) и обновить адрес+QR, если он изменился.

        Зовётся по таймеру, пока панель открыта. QR пересоздаётся только при
        реальной смене адреса — иначе мигал бы каждый тик.
        """
        if self._widget is None:
            return
        endpoints = self._current_endpoints()
        if endpoints == self._last_endpoints:
            return
        self._last_endpoints = endpoints
        self._apply_connection(endpoints)

    def _start_addr_timer(self) -> None:
        """Запустить периодическую проверку смены сети (пока панель открыта)."""
        if self._widget is None:
            return
        if self._addr_timer is None:
            self._addr_timer = QTimer(self._widget)
            self._addr_timer.setInterval(4000)
            self._addr_timer.timeout.connect(self._maybe_refresh_address)
        self._addr_timer.start()

    def _stop_addr_timer(self) -> None:
        """Остановить проверку смены сети (панель скрыта)."""
        if self._addr_timer is not None:
            self._addr_timer.stop()

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
        """Привязать статус и последнее слово к state store."""
        self._unbind()
        bindings = getattr(self._runtime, "bindings", None)
        if bindings is None or self._widget is None:
            return
        base = "processes.*.state.phone"
        self._handles.append(
            bindings.bind(
                f"{base}.connection.running",
                self._widget.status_label,
                "text",
                formatter=lambda v: "Статус: включён ✓" if v else "Статус: выключен",
            )
        )
        self._handles.append(
            bindings.bind(
                f"{base}.word",
                self._widget.word_label,
                "text",
                formatter=lambda v: f"Последнее слово: {v}" if v else "Последнее слово: —",
            )
        )
        # Превью фото: bindings вызовет widget.set_thumb_b64(value) (fallback-метод).
        self._handles.append(bindings.bind(f"{base}.photo_thumb", self._widget, "set_thumb_b64"))


def build_phone_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Телефон",
) -> SectionSpec:
    """SectionSpec для секции «Телефон» (lazy). parent_key — для группировки."""
    section = _PhoneSection(services, runtime)
    return SectionSpec(
        key="__phone__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
