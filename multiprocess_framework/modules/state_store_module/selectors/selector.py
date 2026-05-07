"""selector.py — Вычисляемое производное состояние (аналог MobX computed / Reselect).

Selector автоматически пересчитывает значение при изменении зависимостей
и публикует результат в дерево: selectors.{name} = computed_value.

SelectorRegistry управляет жизненным циклом selectors: регистрация,
подписка на зависимости, автоматический recompute, unregister.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from ..core.delta import Delta
from ..core.subscription_manager import SubscriptionManager
from ..core import iter_matches, match_pattern, split_pattern
from ..core.tree_store import TreeStore


# ---------------------------------------------------------------------------
# Совместимость: тонкая обёртка над общим iter_matches.
# Сохранена ради тестов test_selectors.py, которые проверяют сбор по паттерну
# через приватный helper. Реальная логика обхода теперь живёт в
# core/glob_walker.py — единый walker для всего модуля.
# ---------------------------------------------------------------------------

def _collect_values_by_pattern(root: Dict[str, Any], pattern: str) -> Dict[str, Any]:
    """Собрать `{полный_точечный_путь: значение}` по glob-паттерну.

    Тонкая обёртка над `core.iter_matches`. Оставлена для обратной
    совместимости с тестами/прикладным кодом, импортировавшим этот хелпер.
    """
    return dict(iter_matches(root, pattern))


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

class Selector:
    """Вычисляемое значение, зависящее от нескольких путей в дереве.

    Кэширует результат, пересчитывает только при изменении зависимостей.
    Публикует результат в дерево: selectors.{name} = computed_value.
    Подписчики могут подписаться на selectors.{name} как на обычный путь.

    Пример:
        avg_fps = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda values: sum(values.values()) / max(len(values), 1),
        )
        registry.register(avg_fps)

        # Теперь selectors.avg_fps автоматически обновляется
        # Подписка: store.subscribe("selectors.avg_fps", callback)
    """

    def __init__(
        self,
        name: str,
        dependencies: List[str],
        compute: Callable[[Dict[str, Any]], Any],
    ) -> None:
        if not name:
            raise ValueError("Selector name не может быть пустым")
        if not dependencies:
            raise ValueError("Selector должен иметь хотя бы одну зависимость")

        self._name = name
        self._dependencies = list(dependencies)
        self._compute = compute
        self._cached_value: Any = None
        self._has_cached = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> str:
        """Путь в дереве: selectors.{name}"""
        return f"selectors.{self._name}"

    @property
    def dependencies(self) -> List[str]:
        """Список паттернов зависимостей (копия)."""
        return list(self._dependencies)

    @property
    def cached_value(self) -> Any:
        """Последнее вычисленное значение (или None если ещё не вычислялось)."""
        return self._cached_value

    def recompute(self, store: TreeStore) -> Any:
        """Пересчитать значение на основе текущего состояния store.

        1. Для каждого dependency-паттерна собирает все совпавшие пути и значения.
        2. Объединяет в единый dict {path: value}.
        3. Вызывает compute(values_dict).
        4. Обновляет кэш.

        Returns:
            Новое вычисленное значение.
        """
        # Собираем значения по всем паттернам зависимостей через единый walker
        values: Dict[str, Any] = {}
        root = store.get_subtree("")
        for pattern in self._dependencies:
            for path, value in iter_matches(root, pattern):
                values[path] = value

        # Вычисляем новое значение
        new_value = self._compute(values)
        self._cached_value = new_value
        self._has_cached = True
        return new_value


# ---------------------------------------------------------------------------
# SelectorRegistry
# ---------------------------------------------------------------------------

class SelectorRegistry:
    """Менеджер всех selectors.

    Регистрирует selectors, подписывается на зависимости через SubscriptionManager,
    автоматически пересчитывает при изменениях и публикует результат в дерево.

    Потокобезопасен.
    """

    # Имя подписчика для SubscriptionManager
    _SUBSCRIBER_PREFIX = "__selector__"

    def __init__(
        self,
        store: TreeStore,
        subscription_manager: Optional[SubscriptionManager] = None,
    ) -> None:
        self._store = store
        self._sub_manager = subscription_manager or SubscriptionManager()
        self._lock = threading.RLock()

        # name → Selector
        self._selectors: Dict[str, Selector] = {}
        # name → list[sub_id] (ID подписок в SubscriptionManager)
        self._sub_ids: Dict[str, List[str]] = {}
        # Флаг для предотвращения рекурсивных пересчётов
        self._recomputing: bool = False

    def register(self, selector: Selector) -> None:
        """Зарегистрировать selector и подписаться на его зависимости.

        При регистрации сразу вычисляет начальное значение и публикует в дерево.

        Raises:
            ValueError: если selector с таким именем уже зарегистрирован.
        """
        with self._lock:
            if selector.name in self._selectors:
                raise ValueError(
                    f"Selector '{selector.name}' уже зарегистрирован"
                )

            self._selectors[selector.name] = selector

            # Подписываемся на все зависимости
            subscriber_name = f"{self._SUBSCRIBER_PREFIX}{selector.name}"
            sub_ids: List[str] = []
            for pattern in selector.dependencies:
                sub_id = self._sub_manager.subscribe(
                    pattern=pattern,
                    subscriber=subscriber_name,
                    # Игнорируем изменения от самих selectors,
                    # чтобы не зациклиться
                    exclude_sources=("selector",),
                )
                sub_ids.append(sub_id)
            self._sub_ids[selector.name] = sub_ids

            # Вычисляем начальное значение и публикуем
            new_value = selector.recompute(self._store)
            self._store.set(selector.path, new_value, source="selector")

    def unregister(self, name: str) -> None:
        """Удалить selector и его подписки.

        Также удаляет значение из дерева (selectors.{name}).

        Raises:
            KeyError: если selector с таким именем не найден.
        """
        with self._lock:
            if name not in self._selectors:
                raise KeyError(f"Selector '{name}' не зарегистрирован")

            # Удаляем подписки
            subscriber_name = f"{self._SUBSCRIBER_PREFIX}{name}"
            self._sub_manager.unsubscribe_all(subscriber_name)
            del self._sub_ids[name]

            # Удаляем из реестра
            del self._selectors[name]

            # Удаляем значение из дерева
            self._store.delete(f"selectors.{name}", source="selector")

    def get(self, name: str) -> Any:
        """Получить текущее значение selector.

        Returns:
            Кэшированное значение selector.

        Raises:
            KeyError: если selector с таким именем не зарегистрирован.
        """
        with self._lock:
            if name not in self._selectors:
                raise KeyError(f"Selector '{name}' не зарегистрирован")
            return self._selectors[name].cached_value

    def list(self) -> List[str]:
        """Список имён зарегистрированных selectors."""
        with self._lock:
            return list(self._selectors.keys())

    def handle_delta(self, delta: Delta) -> None:
        """Обработать delta — пересчитать затронутые selectors.

        Вызывается DeltaDispatcher'ом или вручную.
        Один вызов handle_delta пересчитывает ВСЕ затронутые selectors
        (но каждый — максимум один раз).

        Игнорирует дельты от source="selector" (предотвращение зацикливания).
        """
        # Не реагируем на собственные изменения
        if delta.source == "selector":
            return

        with self._lock:
            # Защита от рекурсии (на случай если store.set вызовет handle_delta)
            if self._recomputing:
                return

            # Находим все selectors, чьи зависимости затронуты этой delta
            affected = self._find_affected(delta)
            if not affected:
                return

            self._recomputing = True
            try:
                for selector in affected:
                    old_value = selector.cached_value
                    new_value = selector.recompute(self._store)
                    # Публикуем в дерево только если значение изменилось
                    if new_value != old_value:
                        self._store.set(
                            selector.path, new_value, source="selector"
                        )
            finally:
                self._recomputing = False

    def _find_affected(self, delta: Delta) -> List[Selector]:
        """Найти все selectors, чьи зависимости совпадают с путём delta.

        Использует match_pattern из core для проверки
        совпадения каждого dependency-паттерна с путём delta.
        """
        path_segs = tuple(delta.path.split(".")) if delta.path else ()
        affected: List[Selector] = []

        for selector in self._selectors.values():
            for pattern in selector.dependencies:
                pattern_segs = split_pattern(pattern)
                if match_pattern(pattern_segs, path_segs):
                    affected.append(selector)
                    break  # один selector — один recompute, даже если несколько match

        return affected
