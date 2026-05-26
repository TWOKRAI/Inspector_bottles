"""test_recipe_state_adapter.py — Unit-тесты RecipeStateAdapter (Task 5.5).

Проверяют:
1. sync_domain_to_state публикует active и available в StateProxy.
2. _on_state_active_changed вызывает RecipeManager.set_active.
3. Anti-loop: эхо-изменение не вызывает повторный set_active.
4. None-значение дельты не вызывает set_active.
5. sync_state_to_domain загружает active из StateProxy в RecipeManager.
6. sync_state_to_domain с None пропускает set_active.
7. disconnect() очищает _sub_ids.

Все тесты используют mock StateProxy (MagicMock) и простой FakeRecipeManager.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.5
"""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase
from multiprocess_prototype.backend.state.adapters.recipe_adapter import RecipeStateAdapter


# ---------------------------------------------------------------------------
# Вспомогательные объекты
# ---------------------------------------------------------------------------


class FakeRecipeManager:
    """Простой fake-менеджер рецептов для тестов."""

    def __init__(self, active: str | None = None, available: list[str] | None = None) -> None:
        self._active = active
        self._available = available or []
        self.set_active_calls: list[str] = []
        self.set_active_return = True

    def get_active(self) -> str | None:
        return self._active

    def list(self) -> list[str]:
        return list(self._available)

    def set_active(self, slug: str) -> bool:
        self.set_active_calls.append(slug)
        if self.set_active_return:
            self._active = slug
        return self.set_active_return


def _make_proxy() -> MagicMock:
    """Создать mock StateProxy с методами subscribe/unsubscribe/set/get."""
    proxy = MagicMock()
    # subscribe возвращает уникальный sub_id (строку)
    proxy.subscribe.return_value = "sub_id_001"
    return proxy


def _make_delta(path: str, new_value: object, old_value: object = None) -> Delta:
    """Создать Delta с нужными значениями."""
    return Delta(path=path, old_value=old_value, new_value=new_value, source="test")


def _connected_adapter(
    manager: FakeRecipeManager,
    proxy: MagicMock,
) -> RecipeStateAdapter:
    """Вспомогательная фабрика: создать и подключить адаптер."""
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=proxy)
    adapter.connect()
    return adapter


# ---------------------------------------------------------------------------
# Тест 1: issubclass (контракт наследования)
# ---------------------------------------------------------------------------


def test_recipe_state_adapter_is_subclass_of_base():
    """RecipeStateAdapter обязан наследовать StateAdapterBase."""
    assert issubclass(RecipeStateAdapter, StateAdapterBase)


# ---------------------------------------------------------------------------
# Тест 2: sync_domain_to_state — публикует active
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_sets_active():
    """sync_domain_to_state вызывает proxy.set('recipes.active', 'cup')."""
    manager = FakeRecipeManager(active="cup", available=[])
    proxy = _make_proxy()
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=proxy)

    adapter.sync_domain_to_state()

    # Проверяем, что среди вызовов set был ("recipes.active", "cup")
    proxy.set.assert_any_call("recipes.active", "cup")


# ---------------------------------------------------------------------------
# Тест 3: sync_domain_to_state — публикует available
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_sets_available():
    """sync_domain_to_state вызывает proxy.set('recipes.available', [...])."""
    manager = FakeRecipeManager(active=None, available=["a", "b"])
    proxy = _make_proxy()
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=proxy)

    adapter.sync_domain_to_state()

    proxy.set.assert_any_call("recipes.available", ["a", "b"])


# ---------------------------------------------------------------------------
# Тест 4: _on_state_active_changed вызывает set_active
# ---------------------------------------------------------------------------


def test_on_state_active_changed_calls_set_active():
    """Delta с path='recipes.active', new_value='bottle' → set_active('bottle') вызван."""
    manager = FakeRecipeManager(active=None)
    proxy = _make_proxy()
    adapter = _connected_adapter(manager, proxy)

    delta = _make_delta("recipes.active", new_value="bottle")
    adapter._on_state_active_changed([delta])

    assert "bottle" in manager.set_active_calls


# ---------------------------------------------------------------------------
# Тест 5: anti-loop — sync_domain_to_state не вызывает повторный set_active
# ---------------------------------------------------------------------------


def test_anti_loop_prevents_echo():
    """Адаптер публикует active → получает эхо-delta → set_active НЕ вызывается повторно."""
    manager = FakeRecipeManager(active="cup", available=[])
    proxy = _make_proxy()
    adapter = _connected_adapter(manager, proxy)

    # Вызываем sync — адаптер пометит "recipes.active" как pending и вызовет proxy.set
    adapter.sync_domain_to_state()

    # Симулируем эхо-delta (адаптер сам вызвал set → StateProxy вернул дельту обратно)
    echo_delta = _make_delta("recipes.active", new_value="cup")
    adapter._on_state_active_changed([echo_delta])

    # set_active НЕ должен был вызываться (pending поглотил эхо)
    assert manager.set_active_calls == []


# ---------------------------------------------------------------------------
# Тест 6: delta.new_value is None → set_active НЕ вызывается
# ---------------------------------------------------------------------------


def test_none_active_not_propagated():
    """Delta с new_value=None → RecipeManager.set_active НЕ вызывается."""
    manager = FakeRecipeManager(active="cup")
    proxy = _make_proxy()
    adapter = _connected_adapter(manager, proxy)

    none_delta = _make_delta("recipes.active", new_value=None)
    adapter._on_state_active_changed([none_delta])

    assert manager.set_active_calls == []


# ---------------------------------------------------------------------------
# Тест 7: sync_state_to_domain — загружает active из proxy в manager
# ---------------------------------------------------------------------------


def test_sync_state_to_domain_loads_active():
    """proxy.get('recipes.active') == 'cup' → recipe_manager.set_active('cup') вызван."""
    manager = FakeRecipeManager(active=None)
    proxy = _make_proxy()
    proxy.get.return_value = "cup"
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=proxy)

    adapter.sync_state_to_domain()

    assert "cup" in manager.set_active_calls


# ---------------------------------------------------------------------------
# Тест 8: sync_state_to_domain с None — set_active НЕ вызывается
# ---------------------------------------------------------------------------


def test_sync_state_to_domain_none_skipped():
    """proxy.get('recipes.active') == None → set_active НЕ вызывается."""
    manager = FakeRecipeManager(active=None)
    proxy = _make_proxy()
    proxy.get.return_value = None
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=proxy)

    adapter.sync_state_to_domain()

    assert manager.set_active_calls == []


# ---------------------------------------------------------------------------
# Тест 9: disconnect() очищает _sub_ids
# ---------------------------------------------------------------------------


def test_unsubscribe_clears_sub_ids():
    """После disconnect() список _sub_ids пуст."""
    manager = FakeRecipeManager()
    proxy = _make_proxy()
    # subscribe возвращает разные id при каждом вызове (для надёжности)
    proxy.subscribe.return_value = "sub_001"

    adapter = _connected_adapter(manager, proxy)
    # После connect должен быть 1 sub_id
    assert len(adapter._sub_ids) == 1

    adapter.disconnect()

    # После disconnect — пуст
    assert adapter._sub_ids == []


# ---------------------------------------------------------------------------
# Тест 10: proxy is None — методы не падают
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_no_proxy_no_crash():
    """sync_domain_to_state с proxy=None не бросает исключений."""
    manager = FakeRecipeManager(active="cup")
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=None)

    # Не должен упасть
    adapter.sync_domain_to_state()


def test_sync_state_to_domain_no_proxy_no_crash():
    """sync_state_to_domain с proxy=None не бросает исключений."""
    manager = FakeRecipeManager(active="cup")
    adapter = RecipeStateAdapter(recipe_manager=manager, state_proxy=None)

    # Не должен упасть
    adapter.sync_state_to_domain()
