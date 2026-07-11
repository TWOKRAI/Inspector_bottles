# -*- coding: utf-8 -*-
"""Тесты teardown вкладки Pipeline (волна B: M-leak-3 + Н-3 + Н-4).

Покрытие:
  - PipelinePresenter.dispose(): отписка обеих EventBus-подписок
    (TopologyReplaced + RecipeActivated), идемпотентность, остановка
    дебаунс-таймера авто-персиста (Н-3);
  - publish после dispose не дёргает handler (реальный EventBus);
  - NodeInspectorPanel.dispose(): снятие cam-подписок — баланс bind/unbind (Н-4);
  - PipelineTab.dispose(): каскад в presenter + inspector + отписка ProcessAdded,
    вызов из closeEvent и по сигналу destroyed.

Refs: plans/2026-07-03_review-and-constructor-plan.md (волна B),
      plans/2026-07-03_god-split-design.md (§0).
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.entities import Topology
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab

from ._helpers import make_pipeline_services


# ------------------------------------------------------------------ #
#  Фейки: EventBus со счётчиками + GuiStateBindings со счётчиками      #
# ------------------------------------------------------------------ #


class _CountingSubscription:
    """Хэндл подписки: считает unsubscribe, повторный вызов — no-op."""

    def __init__(self, bus: "_CountingEventBus", entry: tuple) -> None:
        self._bus = bus
        self._entry = entry
        self._active = True

    def unsubscribe(self) -> None:
        if not self._active:
            return
        self._active = False
        self._bus.unsubscribed += 1
        if self._entry in self._bus.handlers:
            self._bus.handlers.remove(self._entry)

    def __enter__(self) -> "_CountingSubscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.unsubscribe()


class _CountingEventBus:
    """Fake EventBus: считает subscribe/unsubscribe, publish зовёт живые handler'ы."""

    def __init__(self) -> None:
        self.subscribed = 0
        self.unsubscribed = 0
        self.handlers: list[tuple[type, Any]] = []

    def subscribe(self, event_type: type, handler: Any) -> _CountingSubscription:
        self.subscribed += 1
        entry = (event_type, handler)
        self.handlers.append(entry)
        return _CountingSubscription(self, entry)

    def publish(self, event: Any) -> None:
        for event_type, handler in list(self.handlers):
            if isinstance(event, event_type):
                handler(event)


class _FakeBindings:
    """Фейк GuiStateBindings со счётчиками bind/unbind (баланс подписок)."""

    def __init__(self) -> None:
        self.bind_count = 0
        self.unbind_count = 0

    def bind(self, path: str, widget: Any, prop: str = "value", *, formatter: Any = None) -> tuple:
        self.bind_count += 1
        return ("handle", path)

    def unbind(self, handle: Any) -> None:
        self.unbind_count += 1


# ===========================================================================
# PipelinePresenter.dispose()
# ===========================================================================


class TestPresenterDispose:
    """M-leak-3: обе EventBus-подписки presenter'а снимаются в dispose()."""

    def test_dispose_unsubscribes_both_subscriptions(self):
        """Конструктор даёт 2 подписки (TopologyReplaced + RecipeActivated),
        dispose() отписывает обе и хэндлы обнуляются."""
        bus = _CountingEventBus()
        services = make_pipeline_services(events=bus)
        presenter = PipelinePresenter(services)
        assert bus.subscribed == 2

        presenter.dispose()

        assert bus.unsubscribed == 2
        assert not bus.handlers
        assert presenter._topology_sub is None
        assert presenter._recipe_activated_sub is None

    def test_dispose_idempotent(self):
        """Повторный dispose() не падает и не даёт лишних отписок."""
        bus = _CountingEventBus()
        services = make_pipeline_services(events=bus)
        presenter = PipelinePresenter(services)

        presenter.dispose()
        presenter.dispose()

        assert bus.unsubscribed == 2

    def test_publish_before_dispose_reloads_model(self):
        """Контроль позитивного пути: ДО dispose publish(TopologyReplaced)
        перечитывает модель из repo (иначе негативный тест ниже бессмыслен)."""
        bus = EventBus()
        services = make_pipeline_services(events=bus)
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()
        assert "camera" in presenter.model.get_process_names()

        services.topology.save(Topology.from_dict({"processes": [], "wires": []}))
        bus.publish(TopologyReplaced(reason="test-reload"))

        assert "camera" not in presenter.model.get_process_names()

    def test_publish_after_dispose_does_not_invoke_handler(self):
        """После dispose publish(TopologyReplaced) НЕ дёргает handler:
        модель presenter'а остаётся со старым снимком (реальный EventBus)."""
        bus = EventBus()
        services = make_pipeline_services(events=bus)
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()
        assert "camera" in presenter.model.get_process_names()

        presenter.dispose()

        services.topology.save(Topology.from_dict({"processes": [], "wires": []}))
        bus.publish(TopologyReplaced(reason="after-dispose"))

        # Модель не перечитана — presenter отписан.
        assert "camera" in presenter.model.get_process_names()

    def test_dispose_stops_persist_timer(self, qtbot):
        """Н-3: dispose() останавливает дебаунс-таймер авто-персиста layout.

        Таймер — parentless singleShot QTimer; без stop() отложенный timeout
        дёрнул бы _persist_layout_to_recipe после разрушения вкладки.
        """
        services = make_pipeline_services(events=_CountingEventBus())
        presenter = PipelinePresenter(services)
        # on_node_moved → _schedule_layout_persist создаёт и стартует таймер
        # (QApplication уже создан pytest-qt).
        presenter.on_node_moved("camera.capture", 10.0, 20.0)
        timer = presenter._layout.persist_timer
        assert timer is not None
        assert timer.isActive()

        presenter.dispose()

        assert not timer.isActive()
        assert presenter._layout.persist_timer is None

    def test_dispose_clears_scene_and_inspector_refs(self):
        """dispose() разрывает ссылки на Qt-объекты (scene/inspector)."""
        services = make_pipeline_services(events=_CountingEventBus())
        presenter = PipelinePresenter(services)

        presenter.dispose()

        assert presenter._scene is None
        assert getattr(presenter, "_inspector", None) is None


# ===========================================================================
# NodeInspectorPanel.dispose()
# ===========================================================================


class TestInspectorDispose:
    """Н-4: cam-подписки панели снимаются при dispose() (баланс bind/unbind)."""

    def _make_camera_panel(self, qtbot) -> tuple[NodeInspectorPanel, _FakeBindings]:
        """Панель с camera-нодой: _show_camera_actual создал bind-подписки."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _FakeBindings()
        panel.set_services(make_pipeline_services(), bindings=binds)
        panel.show_plugin_node(
            "camera_0.camera_service",
            category="source",
            plugin_name="camera_service",
            process_name="camera_0",
        )
        return panel, binds

    def test_dispose_unbinds_camera_subscriptions(self, qtbot):
        """show camera → dispose() → все bind сняты (баланс 0), хэндлы пусты."""
        panel, binds = self._make_camera_panel(qtbot)
        assert binds.bind_count > 0
        assert len(panel._cam_actual_handles) == binds.bind_count

        panel.dispose()

        assert binds.unbind_count == binds.bind_count
        assert panel._cam_actual_handles == []

    def test_dispose_idempotent(self, qtbot):
        """Повторный dispose() — no-op (хэндлы уже сняты, лишних unbind нет)."""
        panel, binds = self._make_camera_panel(qtbot)
        panel.dispose()
        unbound_after_first = binds.unbind_count

        panel.dispose()

        assert binds.unbind_count == unbound_after_first

    def test_dispose_without_bindings_is_noop(self, qtbot):
        """Панель без bindings (headless-конфигурация) — dispose() не падает."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.dispose()

        assert panel._cam_actual_handles == []


# ===========================================================================
# PipelineTab.dispose() / closeEvent / destroyed
# ===========================================================================


class TestTabDispose:
    """Teardown вкладки: каскад dispose + оба пути уничтожения."""

    def _make_tab(self, qtbot) -> tuple[PipelineTab, _CountingEventBus]:
        bus = _CountingEventBus()
        services = make_pipeline_services(events=bus)
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        return tab, bus

    def test_dispose_unsubscribes_all_event_bus_handles(self, qtbot):
        """3 подписки (TopologyReplaced + RecipeActivated + ProcessAdded) сняты."""
        tab, bus = self._make_tab(qtbot)
        assert bus.subscribed == 3

        tab.dispose()

        assert bus.unsubscribed == 3
        assert not bus.handlers
        assert tab._process_added_sub is None

    def test_dispose_idempotent(self, qtbot):
        """Повторный dispose() — no-op (guard _disposed)."""
        tab, bus = self._make_tab(qtbot)

        tab.dispose()
        tab.dispose()

        assert bus.unsubscribed == 3

    def test_close_event_triggers_dispose(self, qtbot):
        """close() → closeEvent → dispose (штатный Qt-путь)."""
        tab, bus = self._make_tab(qtbot)

        tab.close()

        assert bus.unsubscribed == 3

    def test_destroyed_signal_triggers_dispose(self, qtbot):
        """deleteLater (без close) → сигнал destroyed → dispose.

        Именно так вкладка умирает внутри QTabWidget при разрушении родителя —
        closeEvent при этом не приходит.
        """
        bus = _CountingEventBus()
        services = make_pipeline_services(events=bus)
        tab = PipelineTab(services)
        assert bus.subscribed == 3

        tab.deleteLater()

        qtbot.waitUntil(lambda: bus.unsubscribed == 3, timeout=2000)
