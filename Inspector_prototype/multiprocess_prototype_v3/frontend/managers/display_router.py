"""DisplayRouter — frontend-менеджер display-подписок.

Мост между UI (Display tab, WindowManager) и backend (RouterManager, MemoryManager).
Управляет подписками на камеры через frame_router fan-out, троттлинг FPS,
а также доставкой кадров в окна через callback-механизм.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.routing.frame_router_setup import subscribe_to_camera, unsubscribe_from_camera
from registers.display.presets import LayoutPreset, preset_subscriptions
from registers.display.schemas import DisplaySubscription

if TYPE_CHECKING:
    from backend.routing.throttle_middleware import FrameThrottleMiddleware
    from multiprocess_framework.modules.router_module import RouterManager

logger = logging.getLogger(__name__)

# Паттерны для парсинга source_ref
_RE_CAMERA = re.compile(r"^camera_(\d+)$")
_RE_PROCESSOR = re.compile(r"^processor_(\d+)\.\w+\.\w+$")


class DisplayRouter:
    """Frontend-менеджер подписок на display-каналы.

    Отвечает за:
    - subscribe/unsubscribe через RouterManager (frame_router fan-out)
    - Троттлинг FPS через FrameThrottleMiddleware
    - Подсчёт ссылок на source_ref для lazy SHM аллокации
    - Доставку кадров в окна через callback-механизм
    - Применение layout-пресетов (SINGLE, DUAL, QUAD и т.д.)
    """

    def __init__(
        self,
        router_manager: RouterManager,
        memory_manager: object,
        throttle_middleware: FrameThrottleMiddleware,
        headless: bool = False,
        action_bus: object | None = None,
    ) -> None:
        """Инициализация DisplayRouter.

        Args:
            router_manager: RouterManager для регистрации broadcast-маршрутов.
            memory_manager: MemoryManager для lazy SHM аллокации (используется в Task 6.9).
            throttle_middleware: FrameThrottleMiddleware для ограничения FPS каналов.
            headless: Если True — headless-режим без display-окон (CI/headless pipeline).
                      В этом режиме все вызовы subscribe() — no-op, SHM не аллоцируется.
            action_bus: ActionBus для записи LAYOUT_CHANGE действий (опционально).
        """
        self._router_manager = router_manager
        self._memory_manager = memory_manager
        self._throttle = throttle_middleware
        # Флаг headless-режима: подписки пропускаются, SHM не аллоцируется
        self._headless = headless
        # ActionBus для записи display-действий (может быть None)
        self._action_bus = action_bus

        # Активные подписки: subscription_id → DisplaySubscription
        self._active: dict[str, DisplaySubscription] = {}
        # Подсчёт подписок на каждый source_ref (для lazy SHM)
        self._source_ref_count: dict[str, int] = {}
        # Callback-функции доставки кадров: window_id → callback
        self._frame_callbacks: dict[str, Callable] = {}

        # Единый лок для потокобезопасного доступа к изменяемым структурам
        self._lock = threading.Lock()

        if self._headless:
            logger.info("DisplayRouter запущен в headless-режиме — display-подписки отключены")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def headless(self) -> bool:
        """True если DisplayRouter работает в headless-режиме (без окон)."""
        return self._headless

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def subscribe(self, sub: DisplaySubscription) -> bool:
        """Подписать display-окно на источник кадров.

        Идемпотентно: повторная подписка с тем же subscription_id — no-op (True).

        Args:
            sub: Описание подписки (source_ref, window_id, transform).

        Returns:
            True при успехе или идемпотентном повторе, False при ошибке.
        """
        # Headless-режим: подписки пропускаются, SHM не аллоцируется
        if self._headless:
            logger.info("Headless mode: подписка %s пропущена", sub.subscription_id)
            return False

        with self._lock:
            # Идемпотентность: уже подписан — пропускаем
            if sub.subscription_id in self._active:
                logger.debug(
                    "Подписка %s уже активна, пропуск (идемпотентность)",
                    sub.subscription_id,
                )
                return True

            # Парсим camera_id из source_ref
            camera_id = self._parse_camera_id(sub.source_ref)
            if camera_id is None:
                logger.error(
                    "Не удалось извлечь camera_id из source_ref='%s'",
                    sub.source_ref,
                )
                return False

            # Формируем имя канала для fan-out
            channel_name = self._channel_name(sub.window_id)

            # Регистрируем канал в frame_router fan-out
            ok = subscribe_to_camera(self._router_manager, camera_id, channel_name)
            if not ok:
                logger.error(
                    "Не удалось подписать канал '%s' на камеру %d",
                    channel_name,
                    camera_id,
                )
                return False

            # Настраиваем троттлинг FPS если задан лимит
            if sub.transform.fps_limit:
                self._throttle.set_fps_limit(channel_name, sub.transform.fps_limit)

            # Сохраняем подписку
            self._active[sub.subscription_id] = sub

            # Обновляем счётчик ссылок на source_ref
            prev_count = self._source_ref_count.get(sub.source_ref, 0)
            self._source_ref_count[sub.source_ref] = prev_count + 1

            if prev_count == 0:
                # Первая подписка на этот источник — lazy SHM аллокация
                # Реальная аллокация будет в Task 6.9, пока логируем
                logger.info(
                    "Первая подписка на source_ref='%s' — lazy SHM (placeholder)",
                    sub.source_ref,
                )

            logger.debug(
                "Подписка создана: id=%s, source=%s, window=%s, channel=%s",
                sub.subscription_id,
                sub.source_ref,
                sub.window_id,
                channel_name,
            )
            return True

    def unsubscribe(self, subscription_id: str) -> bool:
        """Отписать display-окно от источника кадров.

        Идемпотентно: отписка несуществующего id — no-op (True).

        Args:
            subscription_id: Идентификатор подписки для удаления.

        Returns:
            True при успехе или идемпотентном повторе, False при ошибке.
        """
        with self._lock:
            # Идемпотентность: подписки нет — no-op
            sub = self._active.pop(subscription_id, None)
            if sub is None:
                logger.debug(
                    "Подписка %s не найдена, пропуск (идемпотентность)",
                    subscription_id,
                )
                return True

            camera_id = self._parse_camera_id(sub.source_ref)
            channel_name = self._channel_name(sub.window_id)

            # Отписываем канал из frame_router fan-out
            if camera_id is not None:
                ok = unsubscribe_from_camera(
                    self._router_manager,
                    camera_id,
                    channel_name,
                )
                if not ok:
                    logger.warning(
                        "Ошибка отписки канала '%s' от камеры %d",
                        channel_name,
                        camera_id,
                    )

            # Декремент счётчика ссылок на source_ref
            count = self._source_ref_count.get(sub.source_ref, 0) - 1
            if count <= 0:
                self._source_ref_count.pop(sub.source_ref, None)
                logger.info(
                    "Последняя подписка на source_ref='%s' удалена — lazy cleanup",
                    sub.source_ref,
                )
            else:
                self._source_ref_count[sub.source_ref] = count

            # Убираем лимит FPS для канала
            self._throttle.remove_fps_limit(channel_name)

            # Убираем callback для окна, если был
            self._frame_callbacks.pop(sub.window_id, None)

            logger.debug(
                "Подписка удалена: id=%s, source=%s, window=%s",
                subscription_id,
                sub.source_ref,
                sub.window_id,
            )
            return True

    def get_active_subscriptions(self) -> list[DisplaySubscription]:
        """Получить список активных display-подписок.

        Returns:
            Копия списка активных подписок.
        """
        with self._lock:
            return list(self._active.values())

    def apply_preset(self, preset: LayoutPreset, camera_ids: list[int]) -> None:
        """Применить layout-пресет: отписать все текущие, подписать новые.

        Args:
            preset: Пресет раскладки (SINGLE, DUAL, QUAD и т.д.).
            camera_ids: Список camera_id для формирования подписок.
        """
        # Снимок подписок до смены (для undo)
        subs_before = (
            [s.model_dump() for s in self.get_active_subscriptions()] if self._action_bus else None
        )

        # Отписываем все текущие подписки
        self.unsubscribe_all()

        # Генерируем новые подписки из пресета
        new_subs = preset_subscriptions(preset, camera_ids)

        # Подписываем каждую
        for sub in new_subs:
            ok = self.subscribe(sub)
            if not ok:
                logger.warning(
                    "Не удалось подписать %s из пресета %s",
                    sub.window_id,
                    preset.value,
                )

        # Запись в bus (если подключён)
        if self._action_bus is not None:
            subs_after = [s.model_dump() for s in self.get_active_subscriptions()]
            from multiprocess_prototype_v3.frontend.actions.builder import ActionBuilder

            action = ActionBuilder.layout_change(preset.value, subs_before, subs_after)
            self._action_bus.record(action)

    def add_frame_callback(self, window_id: str, callback: Callable) -> None:
        """Зарегистрировать callback для доставки кадров в окно.

        Args:
            window_id: Идентификатор окна (например, "win_0").
            callback: Функция вызываемая при получении кадра: callback(frame).
        """
        with self._lock:
            self._frame_callbacks[window_id] = callback

    def remove_frame_callback(self, window_id: str) -> None:
        """Удалить callback доставки кадров для окна.

        Args:
            window_id: Идентификатор окна.
        """
        with self._lock:
            self._frame_callbacks.pop(window_id, None)

    def dispatch_frame(self, channel: str, frame: object) -> None:
        """Доставить кадр в соответствующее окно через callback.

        Извлекает window_id из имени канала (display_{window_id} → window_id),
        находит зарегистрированный callback и вызывает его.

        Args:
            channel: Имя канала (например, "display_win_0").
            frame: Объект кадра для доставки.
        """
        # Извлекаем window_id из channel name: "display_win_0" → "win_0"
        prefix = "display_"
        if not channel.startswith(prefix):
            logger.warning("Неожиданный формат канала: '%s'", channel)
            return

        window_id = channel[len(prefix) :]

        with self._lock:
            callback = self._frame_callbacks.get(window_id)

        # Вызываем callback вне лока, чтобы не блокировать другие операции
        if callback is not None:
            callback(frame)

    def unsubscribe_all(self) -> None:
        """Отписать все активные display-подписки."""
        with self._lock:
            sub_ids = list(self._active.keys())

        # Отписываем по одной (каждый вызов захватывает лок внутри)
        for sub_id in sub_ids:
            self.unsubscribe(sub_id)

    # ------------------------------------------------------------------
    # Приватные хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_camera_id(source_ref: str) -> int | None:
        """Извлечь camera_id из source_ref.

        Поддерживаемые форматы:
        - ``camera_{id}`` → int(id)
        - ``processor_{id}.{region}.{step}`` → int(id)

        Args:
            source_ref: Строка идентификатора источника.

        Returns:
            camera_id как int, или None если формат не распознан.
        """
        # Пробуем формат camera_{id}
        match = _RE_CAMERA.match(source_ref)
        if match:
            return int(match.group(1))

        # Пробуем формат processor_{id}.{region}.{step}
        match = _RE_PROCESSOR.match(source_ref)
        if match:
            return int(match.group(1))

        return None

    @staticmethod
    def _channel_name(window_id: str) -> str:
        """Сформировать имя канала для display-окна.

        Args:
            window_id: Идентификатор окна (например, "win_0").

        Returns:
            Имя канала: ``display_{window_id}``.
        """
        return f"display_{window_id}"


__all__ = ["DisplayRouter"]
