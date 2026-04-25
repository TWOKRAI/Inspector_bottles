"""
Config — runtime-контейнер данных одной конфигурации (логика в ``core/``, не в ``configs/``).

Ответственность: доступ к данным, подписки на изменения, секции, env-fallback.
Загрузка/сохранение файлов и конвертация моделей — не входят в контракт;
делегируются DataConverter при необходимости снаружи.
"""
from __future__ import annotations

import copy
import os
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Union

from multiprocess_framework.modules.data_schema_module.core.helpers import merge_with_defaults


class Config:
    """
    Runtime-контейнер одной конфигурации.

    - Вложенные ключи через точку: ``config.get("database.host")``
    - Потокобезопасность через RLock
    - Подписки на изменения (конкретный ключ или ``"*"`` для всех)
    - Доступ к секциям: ``config.section("database")``
    - Env-fallback: если ключ не найден, ищет в ``{env_prefix}_{KEY}``
    """

    def __init__(
        self,
        initial_data: Optional[Dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
    ) -> None:
        self._data: Dict[str, Any] = copy.deepcopy(initial_data) if initial_data else {}
        self._lock = RLock()
        self._env_prefix: Optional[str] = env_prefix
        self._change_callbacks: Dict[str, List[Callable]] = {}

    # -------------------------------------------------------------------------
    # Основные методы доступа
    # -------------------------------------------------------------------------

    def get(self, key: str, default: Any = None, env_fallback: bool = True) -> Any:
        """Получить значение по dot-notation ключу."""
        with self._lock:
            value = self._traverse(self._data, key)
            if value is _MISSING:
                if env_fallback and self._env_prefix:
                    env_val = self._env_get(key)
                    if env_val is not None:
                        return env_val
                return default
            return value

    def set(self, key: str, value: Any, notify: bool = True) -> Config:
        """Установить значение по dot-notation ключу."""
        with self._lock:
            old_value = self._traverse(self._data, key)
            old_value = None if old_value is _MISSING else old_value
            self._set_internal(self._data, key.split("."), value)
            if notify and old_value != value:
                self._notify(key, old_value, value)
        return self

    def update(self, data: Dict[str, Any]) -> Config:
        """Слить словарь data с текущими данными (рекурсивно, data имеет приоритет)."""
        with self._lock:
            self._data = merge_with_defaults(data, self._data)
            self._notify("*", None, data)
        return self

    def has(self, key: str) -> bool:
        """Проверить наличие ключа."""
        with self._lock:
            return self._traverse(self._data, key) is not _MISSING

    def remove(self, key: str) -> bool:
        """Удалить ключ. Возвращает True если ключ существовал."""
        with self._lock:
            parts = key.split(".")
            container = self._traverse_parent(self._data, parts)
            leaf = parts[-1]
            if container is _MISSING or not isinstance(container, dict) or leaf not in container:
                return False
            old = container[leaf]
            del container[leaf]
            self._notify(key, old, None)
            return True

    def clear(self) -> Config:
        """Очистить все данные."""
        with self._lock:
            old = copy.deepcopy(self._data)
            self._data.clear()
            self._notify("*", old, {})
        return self

    # -------------------------------------------------------------------------
    # Секции
    # -------------------------------------------------------------------------

    def section(self, section_key: str):
        """Вернуть ConfigSection для работы с частью конфигурации."""
        from multiprocess_framework.modules.config_module.sections.config_section import ConfigSection
        return ConfigSection(self, section_key)

    # -------------------------------------------------------------------------
    # Подписки на изменения
    # -------------------------------------------------------------------------

    def subscribe(
        self,
        callback: Optional[Callable] = None,
        key: str = "*",
    ) -> Union[None, Callable]:
        """
        Подписаться на изменения.

        Можно использовать как декоратор::

            @config.subscribe(key="database.host")
            def on_host_change(key, old, new): ...
        """
        if callback is None:
            def decorator(func: Callable) -> Callable:
                self.subscribe(func, key)
                return func
            return decorator
        with self._lock:
            self._change_callbacks.setdefault(key, []).append(callback)
        return None

    def unsubscribe(self, callback: Callable, key: str = "*") -> bool:
        """Отписаться от изменений. Возвращает True если callback был найден."""
        with self._lock:
            callbacks = self._change_callbacks.get(key, [])
            if callback in callbacks:
                callbacks.remove(callback)
                return True
        return False

    # -------------------------------------------------------------------------
    # Свойства
    # -------------------------------------------------------------------------

    @property
    def data(self) -> Dict[str, Any]:
        """Копия всех данных конфигурации."""
        with self._lock:
            return copy.deepcopy(self._data)

    # -------------------------------------------------------------------------
    # Магические методы
    # -------------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, env_fallback=False)
        if value is None and not self.has(key):
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __delitem__(self, key: str) -> None:
        if not self.remove(key):
            raise KeyError(key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __repr__(self) -> str:
        with self._lock:
            return f"Config(keys={list(self._data.keys())})"

    # -------------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # -------------------------------------------------------------------------

    @staticmethod
    def _traverse(data: Dict, key: str) -> Any:
        """Обход вложенной структуры по dot-notation. Возвращает _MISSING если не найдено."""
        node = data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return _MISSING
        return node

    @staticmethod
    def _traverse_parent(data: Dict, parts: List[str]) -> Any:
        """Вернуть родительский dict для последнего элемента parts."""
        node = data
        for part in parts[:-1]:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return _MISSING
        return node

    @staticmethod
    def _set_internal(data: Dict, parts: List[str], value: Any) -> None:
        """Установить значение по списку ключей, создавая промежуточные dict."""
        node = data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def _env_get(self, key: str) -> Optional[Any]:
        """Получить значение из env-переменной с авто-преобразованием типа."""
        env_key = f"{self._env_prefix}_{key.upper().replace('.', '_')}"
        raw = os.getenv(env_key)
        if raw is None:
            return None
        # bool
        if raw.lower() in ("true", "1", "yes", "on"):
            return True
        if raw.lower() in ("false", "0", "no", "off"):
            return False
        # int / float
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    def _notify(self, key: str, old_value: Any, new_value: Any) -> None:
        """Уведомить подписчиков. Вызывается внутри блокировки."""
        for callback in list(self._change_callbacks.get(key, [])):
            try:
                callback(key, old_value, new_value)
            except Exception:
                pass
        if key != "*":
            for callback in list(self._change_callbacks.get("*", [])):
                try:
                    callback(key, old_value, new_value)
                except Exception:
                    pass


class _MissingSentinel:
    """Sentinel для обозначения отсутствующего значения."""
    __slots__ = ()
    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _MissingSentinel()
