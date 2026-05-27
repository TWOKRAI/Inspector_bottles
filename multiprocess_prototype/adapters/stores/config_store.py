# -*- coding: utf-8 -*-
"""
adapters/stores/config_store.py — ConfigStoreFromManager: domain ConfigStore adapter.

Реализует Protocol ConfigStore из domain/protocols/config_store.py
поверх существующего Config из multiprocess_framework.modules.config_module.

Решения (Task D.2b):
  - subscribe() через локальный glob pub-sub (fnmatch по ключам) — backend-agnostic.
    Вместо того чтобы проксировать Config._change_callbacks (внутренний API),
    используем локальный список пар (pattern, handler). При set() вызываем
    backend.set(), затем итерируем _subscribers и нотифицируем совпавшие.
    TODO Phase E: если backend поддерживает свой subscribe — можно проксировать
    через Config.subscribe(key="*", ...) для get notification из других threads.
  - save(): Config не имеет встроенного persist-to-disk метода — делегируем
    callback _save_callback если передан при создании adapter'а.
    По умолчанию (без _save_callback) — no-op с предупреждением в лог.
  - Thread-safety: RLock вокруг _subscribers list и backend.set/get.
  - get_section(): итерируем backend.data (копия dict) — O(n) по числу ключей.
  - list_keys(): итерируем backend.data (копия dict).

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.2b)
"""

from __future__ import annotations

import fnmatch
import logging
import threading
from typing import Any, Callable, Mapping, Sequence

from multiprocess_prototype.domain.protocols.config_store import ConfigStore
from multiprocess_prototype.domain.protocols.event_bus import Subscription

logger = logging.getLogger(__name__)


class _ConfigSubscription:
    """Subscription для ConfigStoreFromManager. Удаляет пару из _subscribers."""

    def __init__(
        self,
        subscribers: list[tuple[str, Callable[[str, Any], None]]],
        pair: tuple[str, Callable[[str, Any], None]],
        lock: threading.RLock,
    ) -> None:
        self._subscribers = subscribers
        self._pair = pair
        self._lock = lock

    def unsubscribe(self) -> None:
        """Отменить подписку. Повторный вызов — no-op."""
        with self._lock:
            if self._pair in self._subscribers:
                self._subscribers.remove(self._pair)

    def __enter__(self) -> "_ConfigSubscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.unsubscribe()


class ConfigStoreFromManager:
    """Adapter поверх multiprocess_framework.modules.config_module.Config.

    Satisfies domain.protocols.config_store.ConfigStore Protocol.

    Конструктор принимает:
      backend    — экземпляр Config из config_module (уже существующий)
      save_callback — опциональный callable() для persist-to-disk.
                     Если не передан — save() выполняет no-op с предупреждением.

    subscribe(): локальный pub-sub (glob по ключам через fnmatch).
    После backend.set() вызываем все _subscribers, чей паттерн совпадает.

    TODO Phase E: рассмотреть проксирование через Config.subscribe(key="*", ...)
    для получения уведомлений об изменениях из других потоков/компонентов.
    """

    def __init__(
        self,
        backend: Any,
        save_callback: Callable[[], None] | None = None,
    ) -> None:
        self._backend = backend
        self._save_callback = save_callback
        self._subscribers: list[tuple[str, Callable[[str, Any], None]]] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Основной API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение по dot-notation ключу."""
        # Config.get() принимает env_fallback=True по умолчанию.
        # Передаём env_fallback=False чтобы поведение было предсказуемым.
        with self._lock:
            return self._backend.get(key, default, env_fallback=False)

    def set(self, key: str, value: Any) -> None:
        """Установить значение. Нотифицирует подписчиков через локальный pub-sub."""
        with self._lock:
            self._backend.set(key, value)
            self._fire_subscribers(key, value)

    def get_section(self, section: str) -> Mapping[str, Any]:
        """Вернуть все ключи секции как плоский dict без секционного префикса.

        Итерируем backend.data (копия dict) — все ключи с точкой расцениваются
        как dot-notation. Ключ ``display.theme`` → секция ``display``, подключ ``theme``.
        """
        prefix = f"{section}."
        raw: dict[str, Any] = self._backend.data  # копия (deepcopy внутри Config)
        result: dict[str, Any] = {}
        # Обходим плоские ключи в data
        self._collect_section(raw, prefix, result)
        return result

    def list_keys(self, prefix: str = "") -> Sequence[str]:
        """Перечислить все dot-notation ключи, начинающиеся с prefix.

        Обходит backend.data (плоский вид через _flatten).
        """
        raw: dict[str, Any] = self._backend.data
        flat = self._flatten(raw)
        return tuple(k for k in flat if k.startswith(prefix))

    def subscribe(self, key_pattern: str, handler: Callable[[str, Any], None]) -> Subscription:
        """Подписаться на изменения ключей по glob-паттерну (fnmatch).

        Локальный pub-sub: при set() вызываем handler(key, new_value)
        если fnmatch.fnmatch(key, key_pattern).

        Возвращает Subscription с unsubscribe() и context manager.
        """
        pair: tuple[str, Callable[[str, Any], None]] = (key_pattern, handler)
        with self._lock:
            self._subscribers.append(pair)
        return _ConfigSubscription(self._subscribers, pair, self._lock)  # type: ignore[return-value]

    def save(self) -> None:
        """Сохранить конфигурацию на диск через save_callback.

        Если save_callback не передан при создании — no-op с предупреждением.
        """
        if self._save_callback is not None:
            self._save_callback()
        else:
            logger.warning(
                "ConfigStoreFromManager.save() вызван без save_callback — "
                "изменения не сохранены на диск. "
                "Передайте save_callback при создании adapter'а."
            )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _fire_subscribers(self, key: str, value: Any) -> None:
        """Нотифицировать подписчиков с паттернами, совпадающими с key."""
        for pattern, handler in list(self._subscribers):
            if fnmatch.fnmatch(key, pattern):
                try:
                    handler(key, value)
                except Exception as exc:
                    logger.error("ConfigStoreFromManager: subscriber handler raised: %s", exc)

    @staticmethod
    def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Рекурсивно преобразовать вложенный dict в плоский dot-notation dict."""
        result: dict[str, Any] = {}
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                result.update(ConfigStoreFromManager._flatten(v, f"{full_key}."))
            else:
                result[full_key] = v
        return result

    @classmethod
    def _collect_section(
        cls,
        raw: dict[str, Any],
        prefix: str,
        result: dict[str, Any],
    ) -> None:
        """Собрать ключи секции из плоского (flatten) представления backend.data."""
        flat = cls._flatten(raw)
        for full_key, value in flat.items():
            if full_key.startswith(prefix):
                sub_key = full_key[len(prefix) :]
                result[sub_key] = value


# Явная проверка что adapter удовлетворяет Protocol — статический тип-контроль.
# Если Protocol изменится — pyright/mypy поймают несоответствие здесь.
def _check_protocol() -> None:  # pragma: no cover
    backend_stub: Any = None
    _: ConfigStore = ConfigStoreFromManager(backend_stub)
    del _


__all__ = [
    "ConfigStoreFromManager",
]
