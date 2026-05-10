"""DisplayWindowManager — менеджер жизненного цикла display-окон.

Владеет всеми display QWidget: создаёт по запросу, отслеживает по window_id,
обрабатывает close events, гарантирует cleanup подписок при уничтожении.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    # PySide6 импортируется только для аннотаций, чтобы не тянуть тяжёлый импорт
    # в контексте, где GUI ещё не инициализирован
    from PySide6.QtWidgets import QWidget

from registers.display.schemas import DisplaySubscription
from registers.display.transform import DisplayTransform

logger = logging.getLogger(__name__)


class DisplayWindowManager:
    """Менеджер lifecycle display-окон.

    Создаёт и уничтожает QWidget-окна отображения видеопотока,
    управляет подписками через DisplayRouter, оповещает подписчиков
    через on_create / on_destroy callback-и.
    """

    def __init__(self, display_router: object) -> None:
        """Инициализация менеджера.

        Args:
            display_router: Экземпляр DisplayRouter для управления подписками.
        """
        self._display_router = display_router

        # Маппинг window_id → виджет окна
        self._windows: dict[str, QWidget] = {}

        # Маппинг window_id → subscription_id (для отписки при destroy)
        self._subscriptions: dict[str, str] = {}

        # Callback-и, вызываемые при создании окна: callback(window_id)
        self._on_create_callbacks: list[Callable[[str], None]] = []

        # Callback-и, вызываемые при уничтожении окна: callback(window_id)
        self._on_destroy_callbacks: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def create_window(
        self,
        window_id: str,
        source_ref: str,
        transform: DisplayTransform | None = None,
    ) -> QWidget:
        """Создать display-окно и подписать на источник кадров.

        Если окно с таким window_id уже существует — оно сначала уничтожается,
        затем создаётся заново.

        Args:
            window_id: Уникальный идентификатор окна (например, "win_0").
            source_ref: Ссылка на источник кадров (например, "camera_0").
            transform: Параметры трансформации кадра. Если None — используются
                       значения по умолчанию (DisplayTransform()).

        Returns:
            Созданный виджет DisplayWindow.
        """
        # Если окно с таким ID уже существует — сначала уничтожаем его
        if window_id in self._windows:
            logger.debug(
                "Окно '%s' уже существует — пересоздание (destroy + create)",
                window_id,
            )
            self.destroy_window(window_id)

        # Lazy import DisplayWindow: виджет создаётся в Task 6.5,
        # поэтому импортируем внутри метода, а не на уровне модуля
        from frontend.widgets.sources.display_window.widget import DisplayWindow  # noqa: PLC0415

        # Создаём виджет окна
        widget = DisplayWindow(window_id=window_id)

        # Устанавливаем recording indicator если source — камера
        camera_id = self._display_router._parse_camera_id(source_ref)
        if camera_id is not None and hasattr(widget, 'set_recording_indicator_for_camera'):
            widget.set_recording_indicator_for_camera(camera_id)

        # Формируем подписку с трансформацией (или дефолтной)
        sub = DisplaySubscription(
            source_ref=source_ref,
            window_id=window_id,
            transform=transform if transform is not None else DisplayTransform(),
        )

        # Регистрируем подписку в DisplayRouter
        ok = self._display_router.subscribe(sub)
        if not ok:
            logger.error(
                "Не удалось подписать окно '%s' на source_ref='%s'",
                window_id,
                source_ref,
            )

        # Регистрируем callback доставки кадров в виджет
        self._display_router.add_frame_callback(window_id, widget.update_frame)

        # Сохраняем виджет и subscription_id
        self._windows[window_id] = widget
        self._subscriptions[window_id] = sub.subscription_id

        # Подключаем сигнал закрытия окна к destroy_window.
        # Используем lambda с default arg, чтобы захватить window_id по значению,
        # а не по ссылке (иначе все лямбды захватят последний window_id в цикле)
        widget.closed.connect(lambda wid=window_id: self.destroy_window(wid))

        # Оповещаем подписчиков о создании окна
        for callback in self._on_create_callbacks:
            try:
                callback(window_id)
            except Exception:
                logger.exception("Ошибка в on_create callback для окна '%s'", window_id)

        logger.info(
            "Окно создано: id='%s', source_ref='%s', sub_id='%s'",
            window_id,
            source_ref,
            sub.subscription_id,
        )
        return widget

    def destroy_window(self, window_id: str) -> None:
        """Уничтожить display-окно и отписать от источника кадров.

        Идемпотентно: если окно с таким window_id не существует — no-op.

        Args:
            window_id: Идентификатор окна для уничтожения.
        """
        # Если окна нет — no-op
        if window_id not in self._windows:
            logger.debug(
                "destroy_window: окно '%s' не найдено, пропуск (no-op)",
                window_id,
            )
            return

        # Извлекаем виджет и subscription_id из хранилищ
        widget = self._windows.pop(window_id)
        subscription_id = self._subscriptions.pop(window_id)

        # Отписываем от DisplayRouter
        self._display_router.unsubscribe(subscription_id)
        self._display_router.remove_frame_callback(window_id)

        # Qt-safe cleanup: deleteLater() безопасно удаляет виджет
        # в следующей итерации event loop, не вызывая проблем с сигналами
        widget.deleteLater()

        # Оповещаем подписчиков об уничтожении окна
        for callback in self._on_destroy_callbacks:
            try:
                callback(window_id)
            except Exception:
                logger.exception("Ошибка в on_destroy callback для окна '%s'", window_id)

        logger.info("Окно уничтожено: id='%s', sub_id='%s'", window_id, subscription_id)

    def destroy_all(self) -> None:
        """Уничтожить все display-окна.

        Собирает список всех window_ids и уничтожает каждое.
        Если окон нет — no-op.
        """
        # Собираем ключи заранее, т.к. destroy_window изменяет _windows
        window_ids = list(self._windows.keys())

        if not window_ids:
            logger.debug("destroy_all: нет активных окон, пропуск")
            return

        logger.info("Уничтожение всех окон (%d шт.)", len(window_ids))
        for window_id in window_ids:
            self.destroy_window(window_id)

    def get_window(self, window_id: str) -> QWidget | None:
        """Получить виджет окна по его идентификатору.

        Args:
            window_id: Идентификатор окна.

        Returns:
            QWidget виджет или None если окно не найдено.
        """
        return self._windows.get(window_id)

    def list_windows(self) -> list[str]:
        """Получить список идентификаторов всех активных окон.

        Returns:
            Список window_id активных окон.
        """
        return list(self._windows.keys())

    def window_count(self) -> int:
        """Получить количество активных окон.

        Returns:
            Количество активных display-окон.
        """
        return len(self._windows)

    # ------------------------------------------------------------------
    # Регистрация callback-ов
    # ------------------------------------------------------------------

    def add_on_create(self, callback: Callable[[str], None]) -> None:
        """Зарегистрировать callback, вызываемый при создании окна.

        Args:
            callback: Функция вида callback(window_id: str) → None.
        """
        self._on_create_callbacks.append(callback)

    def add_on_destroy(self, callback: Callable[[str], None]) -> None:
        """Зарегистрировать callback, вызываемый при уничтожении окна.

        Args:
            callback: Функция вида callback(window_id: str) → None.
        """
        self._on_destroy_callbacks.append(callback)


__all__ = ["DisplayWindowManager"]
