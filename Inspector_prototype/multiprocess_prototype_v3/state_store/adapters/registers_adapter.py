"""registers_adapter.py — Двунаправленный мост RegistersManager <-> StateProxy.

Позволяет 170+ GUI-виджетам продолжать работать через RegistersManager,
при этом все изменения синхронизируются с централизованным StateStore.

Направление 1 (Widget -> StateStore):
    RegistersManager.subscribe_all -> адаптер -> StateProxy.set()

Направление 2 (StateStore -> Widget):
    StateProxy.subscribe("**") -> адаптер -> RegistersManager.notify_field_changed()

Anti-loop: _pending_paths set предотвращает зацикливание при эхо-событиях.
"""
from __future__ import annotations

import logging
from typing import Any

from state_store.core.delta import Delta

logger = logging.getLogger(__name__)


class RegistersStateAdapter:
    """Двунаправленный мост RegistersManager <-> StateProxy.

    path_mapping задаёт маппинг (register_name, field_name) -> state_path.
    Адаптер не знает конкретных регистров — всё через конфигурацию.

    Пример маппинга:
        {("camera", "fps"): "cameras.0.config.fps",
         ("camera", "exposure"): "cameras.0.config.exposure"}
    """

    def __init__(
        self,
        registers_manager: Any,
        state_proxy: Any,
        path_mapping: dict[tuple[str, str], str],
    ) -> None:
        """
        Args:
            registers_manager: RegistersManager из registers_module (duck-typing).
            state_proxy: GuiStateProxy или StateProxy.
            path_mapping: маппинг (register_name, field_name) -> state_path.
        """
        self._rm = registers_manager
        self._proxy = state_proxy
        # Прямой маппинг: (reg, field) -> state_path
        self._path_mapping = dict(path_mapping)
        # Обратный маппинг: state_path -> (reg, field)
        self._reverse_mapping: dict[str, tuple[str, str]] = {
            v: k for k, v in self._path_mapping.items()
        }
        # Anti-loop: пути, для которых мы инициировали set и ждём эхо
        self._pending_paths: set[str] = set()
        # Состояние подключения
        self._connected = False
        # ID подписки на StateProxy (для отписки)
        self._sub_id: str | None = None

    # -------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------

    def connect(self) -> None:
        """Подключить адаптер: подписаться на RegistersManager и StateProxy."""
        if self._connected:
            logger.warning("RegistersStateAdapter: уже подключён, повторный connect() игнорируется")
            return

        # Направление 1: виджет -> StateStore
        self._rm.subscribe_all(self._on_register_changed)

        # Направление 2: StateStore -> виджет
        # exclude_self=False — нам нужны ВСЕ дельты, включая собственные (для anti-loop)
        self._sub_id = self._proxy.subscribe(
            "**", self._on_state_deltas, exclude_self=False,
        )

        self._connected = True
        logger.info(
            "RegistersStateAdapter: подключён, маппингов=%d, sub_id=%s",
            len(self._path_mapping),
            self._sub_id,
        )

    def disconnect(self) -> None:
        """Отключить адаптер: отписаться от RegistersManager и StateProxy."""
        if not self._connected:
            logger.warning("RegistersStateAdapter: не подключён, disconnect() игнорируется")
            return

        # Отписка от RegistersManager
        self._rm.unsubscribe_all(self._on_register_changed)

        # Отписка от StateProxy
        if self._sub_id is not None:
            self._proxy.unsubscribe(self._sub_id)
            self._sub_id = None

        # Очистка pending
        self._pending_paths.clear()
        self._connected = False
        logger.info("RegistersStateAdapter: отключён")

    @property
    def is_connected(self) -> bool:
        """True если адаптер подключён (connect() вызван, disconnect() — нет)."""
        return self._connected

    @property
    def pending_paths(self) -> frozenset[str]:
        """Текущие pending пути (для тестирования/отладки)."""
        return frozenset(self._pending_paths)

    # -------------------------------------------------------------------
    # Направление 1: RegistersManager -> StateProxy
    # -------------------------------------------------------------------

    def _on_register_changed(
        self, register_name: str, field_name: str, value: Any,
    ) -> None:
        """Callback для RegistersManager.subscribe_all.

        Вызывается когда виджет меняет значение через RegistersManager.
        Транслирует изменение в StateProxy.set().

        Args:
            register_name: имя регистра.
            field_name: имя поля.
            value: новое значение.
        """
        key = (register_name, field_name)
        state_path = self._path_mapping.get(key)

        if state_path is None:
            # Нет маппинга — игнорируем (не все поля синхронизируются)
            logger.debug(
                "RegistersStateAdapter: нет маппинга для (%s, %s), пропуск",
                register_name,
                field_name,
            )
            return

        # Anti-loop: помечаем путь как pending до получения эхо
        self._pending_paths.add(state_path)
        logger.debug(
            "RegistersStateAdapter: виджет -> state: %s = %r (path=%s)",
            key,
            value,
            state_path,
        )

        try:
            self._proxy.set(state_path, value)
        except Exception:
            # Если set упал — убираем из pending, чтобы не блокировать обратный путь
            self._pending_paths.discard(state_path)
            logger.exception(
                "RegistersStateAdapter: ошибка proxy.set(%s, %r)",
                state_path,
                value,
            )

    # -------------------------------------------------------------------
    # Направление 2: StateProxy -> RegistersManager
    # -------------------------------------------------------------------

    def _on_state_deltas(self, deltas: list[Delta]) -> None:
        """Callback для StateProxy.subscribe.

        Вызывается когда StateStore рассылает дельты.
        Для каждой дельты проверяет anti-loop и транслирует в
        RegistersManager.notify_field_changed().

        Args:
            deltas: список Delta от StateProxy.
        """
        for delta in deltas:
            path = delta.path

            # Anti-loop: если мы сами инициировали это изменение — skip
            if path in self._pending_paths:
                self._pending_paths.discard(path)
                logger.debug(
                    "RegistersStateAdapter: anti-loop skip для path=%s",
                    path,
                )
                continue

            # Обратный маппинг: state_path -> (register_name, field_name)
            reg_key = self._reverse_mapping.get(path)
            if reg_key is None:
                # Нет маппинга — это изменение не для наших регистров
                continue

            register_name, field_name = reg_key
            logger.debug(
                "RegistersStateAdapter: state -> виджет: %s.%s = %r (path=%s)",
                register_name,
                field_name,
                delta.new_value,
                path,
            )

            try:
                self._rm.notify_field_changed(
                    register_name, field_name, delta.new_value,
                )
            except Exception:
                logger.exception(
                    "RegistersStateAdapter: ошибка notify_field_changed(%s, %s, %r)",
                    register_name,
                    field_name,
                    delta.new_value,
                )
