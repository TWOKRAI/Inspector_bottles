# -*- coding: utf-8 -*-
"""test_recipe_activated.py — Тесты Task 2.3: GUI-подписка на RecipeActivated.

Покрытие:
1. RecipeActivated → presenter.load() вызван (refresh_list обновлён).
2. Orphan-окно (id нет в новом рецепте) закрывается автоматически.
3. Совпадающее окно остаётся открытым и переподключается (не закрывается).
4. Нет активного рецепта (пустой store) → список пуст, все окна закрыты.
5. Событие до вызова bind_event_bus → graceful no-op.
6. teardown() отписывает от EventBus (повторные события игнорируются).
7. DisplaysTab.create интегрирует bind_event_bus (реальный EventBus, не Fake).

Refs: plans/displays-in-recipe/plan.md Task 2.3
"""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import RecipeActivated
from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeDisplayCatalog
from multiprocess_prototype.frontend.widgets.displays.preview_manager import (
    PreviewWindowManager,
)
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import (
    DisplaysPresenter,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_spec(display_id: str = "main") -> DisplaySpec:
    """Создать DisplaySpec-заглушку."""
    return DisplaySpec(
        display_id=display_id,
        display_name=f"Дисплей {display_id}",
        width=1280,
        height=720,
        format="BGR",
        fps_limit=30.0,
        ring_buffer_blocks=3,
    )


def _make_mock_view() -> MagicMock:
    """Создать mock, совместимый с IDisplaysView."""
    view = MagicMock()
    view.get_form_data.return_value = {
        "id": "new_display",
        "name": "Новый дисплей",
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }
    return view


def _make_fake_window(visible: bool = True) -> MagicMock:
    """Создать mock PreviewWindow."""
    w = MagicMock()
    w.isVisible.return_value = visible
    return w


# ---------------------------------------------------------------------------
# Тест 1: RecipeActivated → load() вызван → refresh_list обновлён
# ---------------------------------------------------------------------------


def test_recipe_activated_calls_load():
    """Эмит RecipeActivated → presenter.load() → view.refresh_list вызван."""
    store = FakeDisplayCatalog()
    store.register(_make_spec("cam1"))
    view = _make_mock_view()
    presenter = DisplaysPresenter(store=store, view=view)

    bus = EventBus()
    presenter.bind_event_bus(bus)

    # До события — load() уже вызывался при создании? Нет, presenter не вызывает load() в __init__.
    # Сбрасываем счётчик вызовов.
    view.reset_mock()

    bus.publish(RecipeActivated(slug="test_recipe"))

    # load() должен был вызвать refresh_list
    view.refresh_list.assert_called_once()
    # refresh_list должен получить список с cam1
    args = view.refresh_list.call_args[0][0]
    assert len(args) == 1
    assert args[0].display_id == "cam1"


# ---------------------------------------------------------------------------
# Тест 2: Orphan-окно закрывается при смене рецепта
# ---------------------------------------------------------------------------


def test_orphan_window_closes_on_recipe_change():
    """Окно дисплея, которого нет в новом рецепте (orphan), закрывается."""
    # Store нового рецепта: только "main", НЕТ "orphan_display"
    store = FakeDisplayCatalog()
    store.register(_make_spec("main"))

    view = _make_mock_view()
    presenter = DisplaysPresenter(store=store, view=view)

    window_manager = PreviewWindowManager()
    bus = EventBus()
    presenter.bind_event_bus(bus, window_manager=window_manager)

    # Регистрируем orphan-окно (его id нет в новом store)
    orphan_window = _make_fake_window(visible=True)
    window_manager.register("orphan_display", orphan_window)

    # Регистрируем совпадающее окно (его id ЕСТЬ в новом store)
    matching_window = _make_fake_window(visible=True)
    window_manager.register("main", matching_window)

    # Публикуем RecipeActivated
    bus.publish(RecipeActivated(slug="new_recipe"))

    # Orphan-окно должно быть закрыто
    orphan_window.close.assert_called_once()

    # Совпадающее окно НЕ должно быть закрыто
    matching_window.close.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 3: Совпадающее окно переподключается (не закрывается)
# ---------------------------------------------------------------------------


def test_matching_window_reconnects_not_closed():
    """Окно с совпадающим id остаётся открытым и переподключается."""
    store = FakeDisplayCatalog()
    store.register(_make_spec("display_a"))
    store.register(_make_spec("display_b"))

    view = _make_mock_view()
    presenter = DisplaysPresenter(store=store, view=view)

    window_manager = PreviewWindowManager()
    bus = EventBus()
    mock_router = MagicMock()
    presenter.bind_event_bus(bus, window_manager=window_manager, router_manager=mock_router)

    # Оба дисплея имеют открытые окна
    window_a = _make_fake_window(visible=True)
    window_b = _make_fake_window(visible=True)
    window_manager.register("display_a", window_a)
    window_manager.register("display_b", window_b)

    bus.publish(RecipeActivated(slug="same_recipe"))

    # Ни одно из окон НЕ закрыто (оба display_id есть в новом store)
    window_a.close.assert_not_called()
    window_b.close.assert_not_called()

    # Каждое окно переподписано: unsubscribe + subscribe
    window_a.unsubscribe.assert_called_once()
    window_a.subscribe.assert_called_once_with(mock_router)
    window_b.unsubscribe.assert_called_once()
    window_b.subscribe.assert_called_once_with(mock_router)


# ---------------------------------------------------------------------------
# Тест 4: Пустой store → список пуст, все окна закрыты
# ---------------------------------------------------------------------------


def test_empty_store_closes_all_windows():
    """Нет активного рецепта (пустой store) → список пуст, все окна закрыты."""
    store = FakeDisplayCatalog()  # пустой
    view = _make_mock_view()
    presenter = DisplaysPresenter(store=store, view=view)

    window_manager = PreviewWindowManager()
    bus = EventBus()
    presenter.bind_event_bus(bus, window_manager=window_manager)

    # Открытые окна из предыдущего рецепта
    w1 = _make_fake_window(visible=True)
    w2 = _make_fake_window(visible=True)
    window_manager.register("old_a", w1)
    window_manager.register("old_b", w2)

    # Публикуем событие — store пустой (нет дисплеев нового рецепта)
    bus.publish(RecipeActivated(slug="empty_recipe"))

    # Оба orphan-окна закрыты
    w1.close.assert_called_once()
    w2.close.assert_called_once()

    # refresh_list вызван с пустым списком
    view.refresh_list.assert_called()
    args = view.refresh_list.call_args[0][0]
    assert len(args) == 0


# ---------------------------------------------------------------------------
# Тест 5: Событие до bind_event_bus → graceful no-op
# ---------------------------------------------------------------------------


def test_no_subscription_without_bind():
    """Presenter без bind_event_bus не реагирует на RecipeActivated."""
    store = FakeDisplayCatalog()
    view = _make_mock_view()
    _presenter = DisplaysPresenter(store=store, view=view)

    bus = EventBus()
    # НЕ вызываем bind_event_bus (_presenter намеренно не подписан)

    # Публикуем событие
    bus.publish(RecipeActivated(slug="some_recipe"))

    # view.refresh_list НЕ вызван (presenter не подписан)
    view.refresh_list.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 6: teardown() отписывает от EventBus
# ---------------------------------------------------------------------------


def test_teardown_unsubscribes():
    """После teardown() RecipeActivated больше не вызывает load()."""
    store = FakeDisplayCatalog()
    store.register(_make_spec("main"))
    view = _make_mock_view()
    presenter = DisplaysPresenter(store=store, view=view)

    bus = EventBus()
    presenter.bind_event_bus(bus)

    # Сбрасываем счётчик после init
    view.reset_mock()

    # Первое событие — должно сработать
    bus.publish(RecipeActivated(slug="r1"))
    view.refresh_list.assert_called_once()

    # Teardown
    presenter.teardown()
    view.reset_mock()

    # Второе событие — должно быть проигнорировано
    bus.publish(RecipeActivated(slug="r2"))
    view.refresh_list.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 7: Интеграционный — DisplaysTab.create с реальным EventBus
# ---------------------------------------------------------------------------


def test_displays_tab_integrates_event_bus(qtbot):
    """DisplaysTab.create с реальным EventBus: RecipeActivated → refresh_list."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    # Создаём services с реальным EventBus
    spec_a = _make_spec("display_a")
    svc = make_displays_services(specs={"display_a": spec_a})

    # Заменяем FakeEventBus на реальный EventBus
    from multiprocess_prototype.domain.app_services import AppServices

    real_bus = EventBus()
    svc_with_real_bus = AppServices(
        plugins=svc.plugins,
        services=svc.services,
        displays=svc.displays,
        recipes=svc.recipes,
        registers=svc.registers,
        topology=svc.topology,
        commands=svc.commands,
        events=real_bus,
        auth=svc.auth,
        config=svc.config,
    )

    tab = DisplaysTab.create(svc_with_real_bus)
    qtbot.addWidget(tab)

    # Убеждаемся, что display_a изначально присутствует в nav-списке
    assert "display_a" in tab._key_to_item

    # Добавляем новый дисплей в store (имитирует наполнение backend'ом)
    new_spec = _make_spec("display_b")
    svc_with_real_bus.displays.register(new_spec)  # type: ignore[attr-defined]

    # Публикуем RecipeActivated → вкладка должна перечитать список
    real_bus.publish(RecipeActivated(slug="new_recipe"))

    # display_b должен появиться в nav-списке после обновления
    assert "display_b" in tab._key_to_item
