# -*- coding: utf-8 -*-
"""PreviewWindow — автономное окно превью SHM-канала дисплея.

В Phase 4 реальные кадры в SHM ещё не пишутся — окно показывает placeholder
"Ожидание кадров...". Реальные кадры пойдут в Phase 7 (демо).

Архитектура threading:
    SHM-callback приходит из IPC-потока (или другого процесса).
    Прямой вызов ``QLabel.setPixmap()`` из не-main-потока ведёт к freeze или crash.
    Решение: внутренний ``Signal(object)`` эмитится из callback — Qt автоматически
    делает thread-hop через event loop, и слот ``_update_frame_slot`` вызывается
    уже в main thread.

Подписка:
    ``subscribe()`` вызывает ``router_manager.register_broadcast_route(channel_key, [name])``.
    ``unsubscribe()`` — обратная операция. Если ``router_manager is None`` — graceful no-op.

Паттерн подписки адаптирован из ``frame_router_setup.py`` (subscribe_to_camera /
unsubscribe_from_camera), но упрощён: превью — единственный подписчик на свой канал,
без динамического fan-out.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_framework.modules.display_module import DisplayEntry

if TYPE_CHECKING:
    from multiprocess_framework.modules.router_module import RouterManager

_logger = logging.getLogger(__name__)


class PreviewWindow(QWidget):
    """Автономное окно превью SHM-канала отображения.

    В Phase 4 кадры в SHM ещё не пишутся — окно показывает placeholder.
    Реальные кадры пойдут в Phase 7 (демо).

    Threading:
        - SHM-callback приходит из IPC-потока
        - ``_frame_signal`` эмитится из callback (thread-safe эмит сигнала в Qt)
        - ``_update_frame_slot`` подключён к сигналу — Qt делает thread-hop в main thread

    Attributes:
        _entry: конфигурация дисплея (DisplayEntry).
        _router_manager: ссылка на RouterManager для подписки/отписки (может быть None).
        _subscribed: флаг-guard для idempotent unsubscribe.
        _channel_name: уникальное имя подписчика (id окна).
        _channel_key: ключ маршрута ``display.<id>``.
    """

    # Сигнал для thread-safe передачи frame_data из IPC-потока в main thread.
    # object — т.к. передаём dict с numpy array внутри.
    _frame_signal = Signal(object)

    def __init__(
        self,
        display_entry: DisplayEntry,
        router_manager: Optional["RouterManager"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Создать окно превью для заданного дисплея.

        Args:
            display_entry: конфигурационная запись дисплея из DisplayRegistry.
            router_manager: RouterManager для подписки на broadcast (None → no-op).
            parent: родительский виджет (None → автономное окно).
        """
        super().__init__(parent, Qt.WindowType.Window)
        self._entry = display_entry
        self._router_manager = router_manager
        self._subscribed = False

        # Уникальное имя подписчика — включает id(self) для различения нескольких
        # окон одного дисплея (edge case: пользователь открыл 2 превью одного канала)
        self._channel_name = f"preview_{display_entry.id}_{id(self)}"
        self._channel_key = f"display.{display_entry.id}"

        # --- Заголовок и размеры ---
        self.setWindowTitle(f"Превью: {display_entry.name} ({display_entry.id})")
        w = max(display_entry.width, 320)
        h = max(display_entry.height, 240)
        self.resize(w, h)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Основной label для отображения кадров
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setScaledContents(True)
        self._label.setMinimumSize(320, 240)
        self._label.setText("Ожидание кадров...")
        layout.addWidget(self._label, 1)

        # Строка состояния подписки (внизу окна)
        self._status_label = QLabel("Подписка не активна", self)
        layout.addWidget(self._status_label, 0)

        # Подключаем сигнал к слоту — Qt гарантирует вызов в main thread
        self._frame_signal.connect(self._update_frame_slot)

    # ------------------------------------------------------------------ #
    #  Подписка / Отписка                                                  #
    # ------------------------------------------------------------------ #

    def subscribe(self, router_manager: Optional["RouterManager"] = None) -> None:
        """Подписаться на SHM broadcast-маршрут для этого дисплея.

        Если ``router_manager`` не передан — использует ранее сохранённый.
        Если нет ни того ни другого — graceful no-op с логированием.

        Args:
            router_manager: RouterManager для регистрации маршрута (None → self._router_manager).
        """
        rm = router_manager or self._router_manager
        if rm is None:
            _logger.info(
                "PreviewWindow[%s]: router_manager не передан, подписка пропущена",
                self._entry.id,
            )
            self._status_label.setText("Подписка не активна (нет router)")
            return

        try:
            # Graceful degradation: если метод отсутствует — не ломаемся
            register = getattr(rm, "register_broadcast_route", None)
            if register is None:
                _logger.warning(
                    "PreviewWindow[%s]: router не имеет register_broadcast_route",
                    self._entry.id,
                )
                self._status_label.setText("Подписка не активна (нет метода)")
                return

            register(self._channel_key, [self._channel_name])
            self._router_manager = rm
            self._subscribed = True
            self._status_label.setText(f"Подписан: {self._channel_key}")
            _logger.info(
                "PreviewWindow[%s]: подписан на %s как %s",
                self._entry.id,
                self._channel_key,
                self._channel_name,
            )
        except Exception:
            _logger.exception("PreviewWindow[%s]: ошибка подписки", self._entry.id)
            self._status_label.setText("Ошибка подписки")

    def unsubscribe(self) -> None:
        """Отписаться от broadcast-маршрута (idempotent).

        Безопасно вызывать многократно — повторные вызовы после первого no-op.
        """
        if not self._subscribed:
            return

        try:
            # Пытаемся отписаться через register_broadcast_route с пустым списком
            # (паттерн из frame_router_setup: перезаписываем маршрут без себя)
            rm = self._router_manager
            if rm is not None:
                register = getattr(rm, "register_broadcast_route", None)
                if register is not None:
                    # Убираем себя из подписчиков — перерегистрируем без нашего channel_name
                    # Для простоты в Phase 4: перезаписываем пустым списком (мы единственный подписчик)
                    register(self._channel_key, [])
            _logger.info("PreviewWindow[%s]: отписан от %s", self._entry.id, self._channel_key)
        except Exception:
            _logger.exception("PreviewWindow[%s]: ошибка отписки", self._entry.id)
        finally:
            self._subscribed = False
            self._status_label.setText("Отписан")

    # ------------------------------------------------------------------ #
    #  Frame callback (IPC-поток → main thread через Signal)              #
    # ------------------------------------------------------------------ #

    def _on_frame_received(self, frame_data: dict) -> None:
        """Callback из IPC-потока — НЕ вызывать Qt UI-методы напрямую.

        Эмитит сигнал ``_frame_signal`` — Qt перенаправит вызов в main thread
        через event loop (механизм queued connection).

        Args:
            frame_data: словарь с ключом ``"frame"`` (numpy array) и метаданными.
        """
        self._frame_signal.emit(frame_data)

    @Slot(object)
    def _update_frame_slot(self, frame_data: object) -> None:
        """Слот в main thread — безопасно обновить QLabel pixmap'ом из кадра.

        Вызывается Qt event loop после эмита ``_frame_signal``.
        Конвертирует numpy array → QImage → QPixmap по формату из DisplayEntry.

        Args:
            frame_data: dict с ключом ``"frame"`` (numpy array).
        """
        try:
            if not isinstance(frame_data, dict):
                _logger.debug(
                    "PreviewWindow[%s]: frame_data не dict, пропуск",
                    self._entry.id,
                )
                return

            arr = frame_data.get("frame")
            if arr is None:
                _logger.debug(
                    "PreviewWindow[%s]: frame_data без ключа 'frame', пропуск",
                    self._entry.id,
                )
                return

            qimg = self._numpy_to_qimage(arr, self._entry.format)
            if qimg is None or qimg.isNull():
                _logger.debug(
                    "PreviewWindow[%s]: не удалось конвертировать array в QImage",
                    self._entry.id,
                )
                return

            self._label.setPixmap(QPixmap.fromImage(qimg))
        except Exception:
            _logger.exception("PreviewWindow[%s]: ошибка обновления кадра", self._entry.id)

    # ------------------------------------------------------------------ #
    #  Конвертация numpy → QImage                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _numpy_to_qimage(arr: object, fmt: str) -> QImage | None:
        """Конвертация numpy array в QImage по формату пикселей.

        Поддерживаемые форматы:
            - ``"BGR"``  — 3-канальный, ``QImage.Format_BGR888``
            - ``"RGB"``  — 3-канальный, ``QImage.Format_RGB888``
            - ``"GRAY"`` — 1-канальный (2D array), ``QImage.Format_Grayscale8``
            - ``"RGBA"`` — 4-канальный, ``QImage.Format_RGBA8888``

        Args:
            arr: numpy ndarray (или объект, приводимый к ndarray).
            fmt: формат пикселей из DisplayEntry.format.

        Returns:
            QImage при успешной конвертации, None при ошибке или неизвестном формате.
        """
        try:
            import numpy as np
        except ImportError:
            _logger.warning("PreviewWindow: numpy не установлен, конвертация невозможна")
            return None

        if arr is None:
            return None

        try:
            arr = np.ascontiguousarray(arr)
        except (TypeError, ValueError):
            return None

        # Grayscale: 2D array
        if arr.ndim == 2:
            h, w = arr.shape
            bytes_per_line = w
            return QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)

        # Цветные: 3D array (H, W, C)
        if arr.ndim == 3:
            h, w, c = arr.shape
            if c == 3 and fmt == "BGR":
                bytes_per_line = w * 3
                return QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
            if c == 3 and fmt == "RGB":
                bytes_per_line = w * 3
                return QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            if c == 4 and fmt == "RGBA":
                bytes_per_line = w * 4
                return QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)
            # Фолбэк: 3-канальный без явного формата → BGR (OpenCV default)
            if c == 3:
                bytes_per_line = w * 3
                return QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)

        _logger.warning(
            "PreviewWindow._numpy_to_qimage: неподдерживаемый формат ndim=%s fmt=%s",
            getattr(arr, "ndim", "?"),
            fmt,
        )
        return None

    # ------------------------------------------------------------------ #
    #  Qt lifecycle                                                        #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:  # noqa: N802
        """Отписаться при закрытии окна — предотвращает утечку маршрутов."""
        self.unsubscribe()
        super().closeEvent(event)


# ------------------------------------------------------------------ #
#  Фабрика                                                            #
# ------------------------------------------------------------------ #


def open_for_display(
    display_entry: DisplayEntry,
    router_manager: Optional["RouterManager"] = None,
    parent: Optional[QWidget] = None,
) -> PreviewWindow:
    """Фабрика: создать окно превью, подписаться, показать.

    Удобная обёртка для использования из presenter / tab:
    1. Создаёт ``PreviewWindow``
    2. Если router_manager передан — подписывается
    3. Вызывает ``show()``
    4. Возвращает экземпляр (вызывающий код должен хранить ссылку)

    Args:
        display_entry: конфигурация дисплея.
        router_manager: RouterManager для подписки (None → без подписки).
        parent: родительский виджет (None → автономное окно).

    Returns:
        Открытое и (опционально) подписанное окно превью.
    """
    window = PreviewWindow(
        display_entry,
        router_manager=router_manager,
        parent=parent,
    )
    if router_manager is not None:
        window.subscribe()
    window.show()
    return window
