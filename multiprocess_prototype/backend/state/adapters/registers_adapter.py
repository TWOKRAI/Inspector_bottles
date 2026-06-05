"""registers_adapter.py — Двунаправленный мост RegistersManager <-> StateProxy.

Позволяет 170+ GUI-виджетам продолжать работать через RegistersManager,
при этом все изменения синхронизируются с централизованным StateStore.

Направление 1 (Widget -> StateStore):
    RegistersManager.subscribe_all -> адаптер -> StateProxy.set()

Направление 2 (StateStore -> Widget):
    StateProxy.subscribe("**") -> адаптер -> RegistersManager.notify_field_changed()

Anti-loop: базовый класс StateAdapterBase хранит _pending_paths set и предоставляет
хелперы _mark_pending / _check_and_clear_pending для предотвращения зацикливания.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase


class RegistersStateAdapter(StateAdapterBase):
    """Двунаправленный мост RegistersManager <-> StateProxy.

    path_mapping задаёт маппинг (register_name, field_name) -> state_path.
    Адаптер не знает конкретных регистров — всё через конфигурацию.

    Пример маппинга:
        {("camera", "fps"): "cameras.0.config.fps",
         ("camera", "exposure"): "cameras.0.config.exposure"}

    Args:
        registers_manager: RegistersManager из registers_module (duck-typing).
        path_mapping: маппинг (register_name, field_name) -> state_path.
        state_proxy: GuiStateProxy или StateProxy (опционален, можно bind() позже).
        logger: менеджер логирования (LoggerManager или совместимый).
        stats: менеджер статистики.
        error: менеджер ошибок.
    """

    def __init__(
        self,
        registers_manager: Any,
        path_mapping: dict[tuple[str, str], str],
        state_proxy: Any | None = None,
        logger: Any | None = None,
        stats: Any | None = None,
        error: Any | None = None,
    ) -> None:
        super().__init__(state_proxy=state_proxy, logger=logger, stats=stats, error=error)
        self._rm = registers_manager
        # Прямой маппинг: (reg, field) -> state_path
        self._path_mapping = dict(path_mapping)
        # Обратный маппинг: state_path -> (reg, field)
        self._reverse_mapping: dict[str, tuple[str, str]] = {v: k for k, v in self._path_mapping.items()}

    # -------------------------------------------------------------------
    # StateAdapterBase — реализация абстрактных методов
    # -------------------------------------------------------------------

    def _subscribe_all(self) -> None:
        """Создать подписки: RegistersManager (виджет→state) и StateProxy (state→виджет).

        Вызывается базовым классом из connect().
        """
        # Направление 1: виджет -> StateStore
        self._rm.subscribe_all(self._on_register_changed)

        # Направление 2: StateStore -> виджет
        # exclude_self=False — нам нужны ВСЕ дельты, включая собственные (для anti-loop)
        sub_id = self._proxy.subscribe(
            "**",
            self._on_state_deltas,
            exclude_self=False,
        )
        self._sub_ids.append(sub_id)

        self._log_info(f"RegistersStateAdapter: подписки созданы, маппингов={len(self._path_mapping)}, sub_id={sub_id}")

    def _unsubscribe_all(self) -> None:
        """Отменить все подписки: отписаться от RegistersManager и StateProxy.

        Вызывается базовым классом из disconnect().
        """
        # Отписка от RegistersManager
        self._rm.unsubscribe_all(self._on_register_changed)

        # Отписка от StateProxy (sub_ids заполнены в _subscribe_all)
        for sub_id in self._sub_ids:
            self._proxy.unsubscribe(sub_id)

        self._log_info("RegistersStateAdapter: подписки отменены")

    def sync_domain_to_state(self) -> None:
        """Синхронизировать все регистры из RegistersManager -> StateProxy.

        Для каждой пары (reg, field) из path_mapping читает значение
        из RegistersManager и записывает в StateProxy.
        Полезно при начальной загрузке или reconnect.
        """
        if self._proxy is None:
            self._log_warning("RegistersStateAdapter: sync_domain_to_state — нет proxy")
            return

        for (register_name, field_name), state_path in self._path_mapping.items():
            register = self._rm.get_register(register_name)
            if register is None:
                # RegistersManager не имеет get_field — читаем значение поля
                # с экземпляра регистра (SchemaBase). Нет регистра — нет смысла
                # держать pending: логируем и пропускаем (правило 5).
                self._log_warning(f"sync_domain_to_state: регистр '{register_name}' не найден — пропуск {state_path}")
                continue
            try:
                value = getattr(register, field_name)
                self._mark_pending(state_path)
                self._proxy.set(state_path, value)
            except Exception as exc:
                # Убираем pending при ошибке, чтобы не блокировать обратный путь
                self._pending_paths.discard(state_path)
                self._log_warning(
                    f"sync_domain_to_state: не удалось синхронизировать "
                    f"{register_name}.{field_name} -> {state_path}: {exc}"
                )

    def sync_state_to_domain(self) -> None:
        """Синхронизировать все пути из StateProxy -> RegistersManager.

        Для каждого state_path из маппинга читает значение из StateProxy
        и уведомляет RegistersManager. Полезно при начальной загрузке.
        """
        if self._proxy is None:
            self._log_warning("RegistersStateAdapter: sync_state_to_domain — нет proxy")
            return

        for state_path, (register_name, field_name) in self._reverse_mapping.items():
            try:
                value = self._proxy.get(state_path)
                self._rm.notify_field_changed(register_name, field_name, value)
            except Exception:  # nosec B110 — graceful: путь отсутствует в store, пропускаем
                pass

    # -------------------------------------------------------------------
    # Направление 1: RegistersManager -> StateProxy
    # -------------------------------------------------------------------

    def _on_register_changed(
        self,
        register_name: str,
        field_name: str,
        value: Any,
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
            return

        # Anti-loop: помечаем путь как pending до получения эхо
        self._mark_pending(state_path)

        try:
            self._proxy.set(state_path, value)
        except Exception:
            # Если set упал — убираем из pending, чтобы не блокировать обратный путь
            self._pending_paths.discard(state_path)

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
            if self._check_and_clear_pending(path):
                continue

            # Обратный маппинг: state_path -> (register_name, field_name)
            reg_key = self._reverse_mapping.get(path)
            if reg_key is None:
                # Нет маппинга — это изменение не для наших регистров
                continue

            register_name, field_name = reg_key

            try:
                self._rm.notify_field_changed(
                    register_name,
                    field_name,
                    delta.new_value,
                )
            except Exception:  # nosec B110 — graceful: callback-ошибка не прерывает обработку дельт
                pass


__all__ = ["RegistersStateAdapter"]
