"""Тесты NodeInspectorPanel — включая интеграцию с CardsFieldFactory.
Task E.1: мигрировано на AppServices. set_services вместо set_context.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from PySide6.QtWidgets import QLineEdit

from ._helpers import make_pipeline_services


# ------------------------------------------------------------------ #
#  Вспомогательные фабрики и фикстуры                                 #
# ------------------------------------------------------------------ #


def _make_services_no_rm():
    """AppServices без registers-зависимостей (FakeRegistersBackend пустой)."""
    return make_pipeline_services()


def _make_rm(fields: list):
    """MagicMock RegistersManager, возвращающий заданные FieldInfo.

    G.2: registers_manager — explicit runtime-dep, передаётся в panel.set_services()
    или PipelinePresenter(registers_manager=...), НЕ через services.
    """
    rm = MagicMock()
    rm.get_fields.return_value = fields
    return rm


def _make_field_info(field_name: str, field_type: type = str, default: Any = ""):
    """Создать FieldInfo для теста."""
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

    return FieldInfo(
        plugin_name="test_plugin",
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=None,
        category="test",
    )


class _FakeBindings:
    """Фейк GuiStateBindings — записывает вызовы bind/unbind."""

    def __init__(self) -> None:
        self.bound: list[str] = []
        self.unbound: int = 0

    def bind(self, path, widget, prop="value", *, formatter=None):
        self.bound.append(path)
        return ("h", path)

    def unbind(self, handle) -> None:
        self.unbound += 1


class TestCameraActualReadout:
    """Phase 3: actual-телеметрия камеры в инспекторе."""

    def test_camera_node_shows_actual_and_binds(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _FakeBindings()
        panel.set_services(_make_services_no_rm(), bindings=binds)

        panel.show_plugin_node(
            "camera_0.camera_service",
            category="source",
            plugin_name="camera_service",
            process_name="camera_0",
        )
        assert not panel._cam_section.isHidden()
        base = "processes.camera_0.state.cam.actual"
        assert f"{base}.fps" in binds.bound
        assert f"{base}.width" in binds.bound
        assert f"{base}.fourcc" in binds.bound

    def test_non_camera_node_hides_actual(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _FakeBindings()
        panel.set_services(_make_services_no_rm(), bindings=binds)

        panel.show_plugin_node(
            "proc.color_mask",
            category="processing",
            plugin_name="color_mask",
            process_name="proc",
        )
        assert panel._cam_section.isHidden()

    def test_clear_unbinds_actual(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _FakeBindings()
        panel.set_services(_make_services_no_rm(), bindings=binds)
        panel.show_plugin_node(
            "camera_0.camera_service",
            category="source",
            plugin_name="camera_service",
            process_name="camera_0",
        )
        panel.clear()
        assert binds.unbound > 0
        assert panel._cam_section.isHidden()


def _make_presenter_services(bus=None):
    """AppServices для PipelinePresenter с опциональным action_bus.

    G.2: registers_manager больше не на services — передаётся в PipelinePresenter напрямую.
    """
    return make_pipeline_services(
        topology={"processes": [], "wires": []},
        action_bus=bus,
    )


# ------------------------------------------------------------------ #
#  Оригинальные тесты (backward compatibility)                        #
# ------------------------------------------------------------------ #


class TestNodeInspectorPanel:
    def test_create(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        assert not panel._placeholder.isHidden()
        assert panel._content.isHidden()

    def test_show_node(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.show_node("camera", "source")
        assert panel.current_process == "camera"
        assert panel._placeholder.isHidden()
        assert not panel._content.isHidden()
        assert panel._title.text() == "camera"

    def test_show_node_with_plugins(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        plugins = [{"plugin_name": "capture"}, {"plugin_name": "filter"}]
        panel.show_node("camera", "source", plugins=plugins)
        assert panel._params_section._layout.count() >= 2

    def test_show_node_with_params(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30", "resolution": "1080"})
        assert "fps" in panel._params_section._field_editors
        assert "resolution" in panel._params_section._field_editors
        assert isinstance(panel._params_section._field_editors["fps"], QLineEdit)
        assert panel._params_section._field_editors["fps"].text() == "30"

    def test_clear(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.show_node("camera", "source")
        panel.clear()
        assert panel.current_process == ""
        assert not panel._placeholder.isHidden()
        assert panel._content.isHidden()

    def test_field_changed_signal(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel._params_section._field_editors["fps"].setText("60")
        panel._params_section._field_editors["fps"].editingFinished.emit()
        assert len(signals_received) == 1
        assert signals_received[0] == ("camera", "fps", "60")

    def test_show_different_node_clears_previous(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})
        panel.show_node("processor", "processing", params={"threshold": "128"})
        assert panel.current_process == "processor"
        assert "threshold" in panel._params_section._field_editors
        assert "fps" not in panel._params_section._field_editors


# ------------------------------------------------------------------ #
#  Новые тесты: CardsFieldFactory-ветка                               #
# ------------------------------------------------------------------ #


class TestCardsFieldFactoryBranch:
    def test_cards_branch_activated_when_rm_has_fields(self, qtbot):
        """Если rm.get_fields() возвращает список — создаются FieldEditor."""
        fi = _make_field_info("threshold", int, 128)
        rm = _make_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)
        panel.show_node("camera", "source")

        assert panel._params_section._use_cards is True
        assert "threshold" in panel._params_section._field_editors
        assert not isinstance(panel._params_section._field_editors["threshold"], QLineEdit)

    def test_lineedit_fallback_when_rm_none(self, qtbot):
        """Fallback на QLineEdit если RegistersManager недоступен."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel._params_section._use_cards is False
        assert isinstance(panel._params_section._field_editors["fps"], QLineEdit)

    def test_lineedit_fallback_when_rm_empty_fields(self, qtbot):
        """Fallback на QLineEdit если rm.get_fields() возвращает пустой список."""
        rm = _make_rm([])
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel._params_section._use_cards is False
        assert isinstance(panel._params_section._field_editors["fps"], QLineEdit)

    def test_cards_field_changed_signal_emitted(self, qtbot):
        """Изменение значения через FieldEditor эмитит field_changed."""
        fi = _make_field_info("threshold", int, 128)
        rm = _make_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)
        panel.show_node("my_process", "source")

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        editor = panel._params_section._field_editors["threshold"]
        panel._params_section._on_field_editor_changed("threshold", editor)

        assert len(signals_received) == 1
        process_name, field_name, value = signals_received[0]
        assert process_name == "my_process"
        assert field_name == "threshold"

    def test_no_signal_leak_on_node_switch(self, qtbot):
        """Быстрое переключение нод не приводит к утечкам сигналов."""
        fi_a = _make_field_info("fps", int, 30)
        fi_b = _make_field_info("threshold", int, 128)

        rm = MagicMock()
        rm.get_fields.return_value = [fi_a]

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Переключение: node A → node B
        panel.show_node("node_a", "source")

        rm.get_fields.return_value = [fi_b]
        panel.show_node("node_b", "source")

        assert "fps" not in panel._params_section._field_editors
        assert "threshold" in panel._params_section._field_editors

    def test_set_services_stores(self, qtbot):
        """set_services корректно сохраняет AppServices."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        services = _make_services_no_rm()
        panel.set_services(services)

        assert panel._services is services

    def test_suppress_changes_during_show_node(self, qtbot):
        """Во время show_node _suppress_changes=True, поэтому сигналы не эмитятся."""
        fi = _make_field_info("rate", float, 1.0)
        rm = _make_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel.show_node("camera", "source")

        assert len(signals_received) == 0


# ------------------------------------------------------------------ #
#  Тесты: PipelinePresenter + ActionBus integration                   #
# ------------------------------------------------------------------ #


class TestPresenterInspectorIntegration:
    def test_set_inspector_connects_field_changed(self, qtbot):
        """set_inspector подключает inspector.field_changed к presenter."""
        services = _make_presenter_services()
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)

        # AppServices должен быть передан в panel
        assert panel._services is services


# ------------------------------------------------------------------ #
#  G.4.3: field_changed → dispatch(SetPluginConfig) + undo/redo       #
# ------------------------------------------------------------------ #


class TestFieldDispatch:
    """G.4.3: field_changed → dispatch(SetPluginConfig) → персист + undo/redo.

    Используем реальный orchestrator+store+EventBus (make_pipeline_services_with_orchestrator),
    НЕ MagicMock(spec=AppContext).
    """

    def _make_services_and_presenter(self, qtbot, *, config=None):
        """Сервисы с процессом 'camera' (plugin 'capture', config) + presenter."""
        from ._helpers import make_pipeline_services_with_orchestrator

        topo = {
            "processes": [
                {
                    "process_name": "camera",
                    "plugins": [
                        {
                            "plugin_name": "capture",
                            "config": config or {"threshold": 100, "brightness": 50},
                        }
                    ],
                },
            ],
            "wires": [],
        }
        services = make_pipeline_services_with_orchestrator(topology=topo)
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        return services, presenter, panel

    def test_field_edit_persists_in_topology(self, qtbot):
        """field_changed → SetPluginConfig → значение в topology_repo (персист)."""
        services, presenter, panel = self._make_services_and_presenter(qtbot)

        panel.field_changed.emit("camera", "threshold", 200)

        # Значение должно быть в domain (editor-топология — SSOT)
        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 200

    def test_field_edit_no_scene_reload(self, qtbot):
        """field-edit НЕ вызывает full scene reload (_suppress сработал)."""
        services, presenter, panel = self._make_services_and_presenter(qtbot)

        # Подставим scene-mock для счёта reload
        scene = MagicMock()
        presenter.set_scene(scene)
        # Делаем initial load чтобы scene был инициализирован
        presenter.load_topology_from_config()
        scene.reset_mock()

        panel.field_changed.emit("camera", "threshold", 200)

        # scene.load_from_data НЕ вызван (dispatch обёрнут в _block_signals,
        # _on_topology_replaced гасится _suppress)
        scene.load_from_data.assert_not_called()

    def test_undo_redo_field_roundtrip(self, qtbot):
        """Undo/redo field-config: и domain откатан, и повторён."""
        services, presenter, panel = self._make_services_and_presenter(qtbot)

        # Начальное значение
        topo_before = services.topology.load().to_dict()
        proc = next(p for p in topo_before["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 100

        # Правка
        panel.field_changed.emit("camera", "threshold", 200)
        topo_after = services.topology.load().to_dict()
        proc = next(p for p in topo_after["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 200

        # Undo
        ok = services.commands.undo()
        assert ok is True
        topo_undone = services.topology.load().to_dict()
        proc = next(p for p in topo_undone["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 100

        # Redo
        ok = services.commands.redo()
        assert ok is True
        topo_redo = services.topology.load().to_dict()
        proc = next(p for p in topo_redo["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 200

    def test_undo_field_emits_plugin_config_changed(self, qtbot):
        """G.4.3 Y1: undo field → PluginConfigChanged с откатанным значением.

        rm-sync listener (app.py) подпишется на это событие и вызовет rm.set_value.
        """
        from multiprocess_prototype.domain.events import PluginConfigChanged

        services, presenter, panel = self._make_services_and_presenter(qtbot)

        config_events: list = []
        services.events.subscribe(PluginConfigChanged, lambda ev: config_events.append(ev))

        panel.field_changed.emit("camera", "threshold", 200)
        config_events.clear()

        services.commands.undo()

        assert len(config_events) == 1
        assert config_events[0].field == "threshold"
        assert config_events[0].value == 100

    def test_coalesce_slider_burst(self, qtbot):
        """Серия правок одного поля → одна undo-запись (coalesce_key)."""
        services, presenter, panel = self._make_services_and_presenter(qtbot)

        # Серия slider-тиков (все с одним coalesce_key: set_config:camera:threshold)
        for v in [110, 120, 130, 140, 150]:
            panel.field_changed.emit("camera", "threshold", v)

        # Один undo откатывает всю серию
        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 150

        ok = services.commands.undo()
        assert ok is True
        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 100

        # Больше undo нет (всё в одной записи)
        assert services.commands.can_undo() is False

    def test_domain_error_graceful(self, qtbot, caplog):
        """DomainError (несуществующий процесс) → warning, repo не мутирован."""
        import logging

        services, presenter, panel = self._make_services_and_presenter(qtbot)

        topo_before = services.topology.load().to_dict()

        with caplog.at_level(logging.WARNING):
            panel.field_changed.emit("nonexistent_process", "foo", 42)

        # Repo не изменился
        topo_after = services.topology.load().to_dict()
        assert topo_before == topo_after

        # Warning залогирован
        assert any("SetPluginConfig" in r.message for r in caplog.records)

    def test_suppress_prevents_reentry(self, qtbot):
        """Если _suppress=True — field_changed → no-op (guard от ре-входа)."""
        services, presenter, panel = self._make_services_and_presenter(qtbot)

        presenter._suppress = True
        panel.field_changed.emit("camera", "threshold", 999)

        # Значение НЕ должно измениться
        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "camera")
        assert proc["plugins"][0]["config"]["threshold"] == 100


# ------------------------------------------------------------------ #
#  Task 7a.3: combo target_process + combo display_id                 #
# ------------------------------------------------------------------ #


def _make_services_with_recipe(process_names: list[str]):
    """AppServices с FakeRecipeStore, содержащим процессы из рецепта."""
    from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
    from multiprocess_prototype.domain.tests.conftest import make_test_app_services

    blueprint_processes = [{"process_name": name} for name in process_names]
    raw = {"test_recipe": {"blueprint": {"processes": blueprint_processes, "wires": []}}}
    recipes = FakeRecipeStore(raw=raw, active="test_recipe")

    return make_test_app_services(recipes=recipes)


def _make_display_entry(display_id: str, name: str):
    """Создать mock DisplayEntry."""
    entry = MagicMock()
    entry.id = display_id
    entry.name = name
    return entry


class TestTargetProcessCombo:
    """Тесты combo «Процесс назначения» для plugin-узлов."""

    def test_show_plugin_node_creates_target_process_combo(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor", "output"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_services(services)

        panel.show_plugin_node("camera", "source", target_process="camera")

        assert panel._selector_section._target_process_form.isVisible()
        assert not panel._selector_section._display_id_form.isVisible()

        combo = panel._selector_section._target_process_combo
        assert combo is not None
        assert combo.isEnabled()
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "camera" in items
        assert "processor" in items
        assert "output" in items

    def test_show_plugin_node_selects_current_target_process(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_plugin_node("camera", "source", target_process="processor")

        combo = panel._selector_section._target_process_combo
        assert combo.currentText() == "processor"

    def test_target_process_change_emits_signal(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_plugin_node("node1", "source", target_process="camera")

        received = []
        panel.target_process_changed.connect(lambda nid, proc: received.append((nid, proc)))

        combo = panel._selector_section._target_process_combo
        idx = combo.findText("processor")
        assert idx >= 0
        combo.setCurrentIndex(idx)

        assert len(received) == 1
        assert received[0] == ("node1", "processor")

    def test_show_with_no_recipe_manager_combo_disabled(self, qtbot):
        services = _make_services_no_rm()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_plugin_node("node1", "utility", target_process="")

        combo = panel._selector_section._target_process_combo
        assert not combo.isEnabled() or combo.count() == 0

    def test_show_with_no_services_doesnt_crash(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_plugin_node("node1", "utility", target_process="proc1")

        combo = panel._selector_section._target_process_combo
        assert combo is not None
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_plugin_node(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        received = []
        panel.target_process_changed.connect(lambda *args: received.append(args))

        panel.show_plugin_node("camera", "source", target_process="camera")

        assert len(received) == 0

    def test_show_node_alias_still_works(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel.current_process == "camera"
        assert panel._mode == "plugin"


class TestExecInfo:
    """Phase A: блок «Исполнение» — процесс + воркер/порядок по плагинам."""

    def _exec_texts(self, panel) -> str:
        from PySide6.QtWidgets import QLabel

        lay = panel._exec_section._layout
        parts = []
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QLabel):
                parts.append(w.text())
        return " | ".join(parts)

    def test_processing_plugin_shows_process_and_pipeline_executor(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "preprocessor",
            "processing",
            plugin_name="resize",
            plugins=[{"plugin_name": "resize", "category": "processing"}],
        )
        texts = self._exec_texts(panel)
        assert "preprocessor" in texts
        assert "pipeline_executor" in texts

    def test_source_plugin_shows_own_worker(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "camera_0",
            "source",
            plugin_name="capture",
            plugins=[{"plugin_name": "capture", "category": "source"}],
        )
        assert "source_producer_capture" in self._exec_texts(panel)

    def test_multi_plugin_chain_steps(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "capture_proc",
            "source",
            plugin_name="capture",
            plugins=[
                {"plugin_name": "capture", "category": "source"},
                {"plugin_name": "resize", "category": "processing"},
                {"plugin_name": "region_split", "category": "processing"},
            ],
        )
        texts = self._exec_texts(panel)
        # source — свой поток; два processing — шаги 1/2 и 2/2 в pipeline_executor
        assert "source_producer_capture" in texts
        assert "шаг 1/2" in texts and "шаг 2/2" in texts

    def test_exec_info_cleared_for_display_node(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "preprocessor",
            "processing",
            plugin_name="resize",
            plugins=[{"plugin_name": "resize", "category": "processing"}],
        )
        panel.show_display_node("main", "main", "Основной дисплей")
        assert panel._exec_section._layout.count() == 0


class TestPluginNameFieldResolution:
    """Issue: поля параметров резолвятся по plugin_name (имя регистра), а не
    по node_id (process_name) — тот же путь, что вкладка Plugins."""

    def test_fields_resolved_by_plugin_name(self, qtbot):
        """show_plugin_node(plugin_name=...) зовёт rm.get_fields с ИМЕНЕМ ПЛАГИНА."""
        rm = _make_rm([_make_field_info("scale_factor", float, 1.0)])
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        # node_id (процесс) ≠ plugin_name (регистр)
        panel.show_plugin_node("preprocessor", "processing", plugin_name="resize")

        rm.get_fields.assert_called_with("resize")
        assert panel._params_section._use_cards is True
        # _current_process остаётся process_name — туда уйдёт SetPluginConfig
        assert panel.current_process == "preprocessor"

    def test_plugin_name_empty_falls_back_to_node_id(self, qtbot):
        """Без plugin_name (legacy) — fallback на node_id."""
        rm = _make_rm([_make_field_info("threshold", int, 128)])
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        panel.show_plugin_node("detector", "processing")

        rm.get_fields.assert_called_with("detector")

    def test_config_values_applied_to_fields(self, qtbot):
        """params (config плагина) проставляются в редакторы полей."""
        rm = _make_rm([_make_field_info("scale_factor", float, 1.0)])
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(_make_services_no_rm(), registers_manager=rm)

        panel.show_plugin_node(
            "preprocessor",
            "processing",
            plugin_name="resize",
            params={"scale_factor": 2.5},
        )

        assert "scale_factor" in panel._params_section._field_editors


class TestDisplayIdCombo:
    """Тесты combo «Display» для display-узлов."""

    def _make_display_services(self, entries):
        """Создать services с DisplayCatalog для display combo."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        displays = MagicMock()
        display_specs = tuple(DisplaySpec(display_id=e.id, display_name=e.name) for e in entries)
        displays.list_displays.return_value = display_specs
        displays.resolve.side_effect = lambda did: next((s for s in display_specs if s.display_id == did), None)

        from multiprocess_prototype.domain.tests.conftest import make_test_app_services

        return make_test_app_services(displays=displays)

    def test_show_display_node_creates_display_id_combo(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной дисплей"),
            _make_display_entry("debug_view", "Отладочный вид"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_services(services)

        panel.show_display_node("disp1", "main_output", "Основной дисплей")

        assert panel._selector_section._display_id_form.isVisible()
        assert not panel._selector_section._target_process_form.isVisible()

        combo = panel._selector_section._display_id_combo
        assert combo is not None
        assert combo.isEnabled()
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "main_output" in ids
        assert "debug_view" in ids

    def test_show_display_node_selects_current_display_id(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_display_node("disp1", "debug", "Отладка")

        combo = panel._selector_section._display_id_combo
        assert combo.itemData(combo.currentIndex()) == "debug"

    def test_display_id_change_emits_signal(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_display_node("disp1", "main_output", "Основной")

        received = []
        panel.display_id_changed.connect(lambda nid, did: received.append((nid, did)))

        combo = panel._selector_section._display_id_combo
        target_idx = -1
        for i in range(combo.count()):
            if combo.itemData(i) == "debug":
                target_idx = i
                break
        assert target_idx >= 0
        combo.setCurrentIndex(target_idx)

        assert len(received) == 1
        assert received[0] == ("disp1", "debug")

    def test_display_combo_disabled_when_no_services(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_display_node("disp1", "some_id", "")

        combo = panel._selector_section._display_id_combo
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_display_node(self, qtbot):
        entries = [_make_display_entry("main_output", "Основной")]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        received = []
        panel.display_id_changed.connect(lambda *args: received.append(args))

        panel.show_display_node("disp1", "main_output", "Основной")

        assert len(received) == 0

    def test_refresh_display_combo_updates_entries(self, qtbot):
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        entries = [_make_display_entry("main_output", "Основной")]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_display_node("disp1", "main_output", "Основной")

        # Добавить новый дисплей в реестр
        new_specs = (
            DisplaySpec(display_id="main_output", display_name="Основной"),
            DisplaySpec(display_id="secondary", display_name="Вторичный"),
        )
        services.displays.list_displays.return_value = new_specs

        panel.refresh_display_combo()

        combo = panel._selector_section._display_id_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "secondary" in ids
